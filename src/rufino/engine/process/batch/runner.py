"""Top-level orchestration for `rufino process-batch`.

Six stages: STAGE -> PLAN -> DISPATCH -> VALIDATE+RETRY -> Q&A collect ->
CONSOLIDATE (or naive fallback) -> COMMIT.
"""
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from rufino.engine.process.batch.committer import commit
from rufino.engine.process.batch.consolidator import (
    ConsolidationPlan,
    run_consolidator,
)
from rufino.engine.process.batch.dispatcher import dispatch
from rufino.engine.process.batch.errors import BatchError
from rufino.engine.process.batch.planner import build_plan
from rufino.engine.process.batch.qa_pending import (
    collect_pending,
    write_questions_to_vault,
)
from rufino.engine.process.batch.retry import retry_failed
from rufino.engine.process.batch.stager import stage_corpus
from rufino.engine.process.batch.validator import validate_worker_output
from rufino.engine.process.batch.worker_prompt import (
    build_worker_system_prompt,
)
from rufino.engine.process.manifest import parse_worker_manifest
from rufino.runtime.transaction_log import TransactionLog
from rufino.runtime.vault_slug import compute_vault_slug


@dataclass(frozen=True)
class BatchRunResult:
    run_id: str
    dry_run: bool
    notes_total: int = 0
    notes_ok: int = 0
    notes_failed: int = 0
    notes_pending_qa: int = 0
    plan_path: Path | None = None
    commit_skipped: bool = False


def _new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")


def _gather_concepts_top_n(vault_root: Path, n: int = 30) -> list[str]:
    conceptos = vault_root / "conceptos"
    if not conceptos.exists():
        return []
    return sorted([p.stem for p in conceptos.glob("*.md")])[:n]


def _ensure_gitignore(vault_root: Path) -> None:
    """Lazy migration: add `.rufino/runs/` to vault's .gitignore if present."""
    gi = vault_root / ".gitignore"
    if not gi.exists():
        return
    text = gi.read_text(encoding="utf-8")
    line = ".rufino/runs/"
    if line in text:
        return
    if not text.endswith("\n"):
        text += "\n"
    text += line + "\n"
    gi.write_text(text, encoding="utf-8")


def _naive_commit_plan(
    run_dir: Path, passed, destination_template: str,
) -> ConsolidationPlan:
    from rufino.engine.process.helpers.frontmatter import parse_frontmatter
    moves = []
    tag_map: dict[str, list[str]] = {}
    for nv in passed:
        slug = nv.slug
        try:
            fm, _ = parse_frontmatter(nv.augmented_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        variables = {k: v for k, v in fm.items() if isinstance(v, str)}
        variables.setdefault("slug", slug)
        try:
            dest_rel = destination_template.format(**variables)
        except KeyError:
            continue
        rel_from = nv.augmented_path.relative_to(run_dir)
        moves.append({"from": str(rel_from), "to": dest_rel})
        for tag in fm.get("tags", []):
            tag_map.setdefault(tag, []).append(slug)
    return ConsolidationPlan(
        moves=moves, concept_writes=[],
        tag_index_updates=[{"tag": t, "notes": ns} for t, ns in tag_map.items()],
        log_entries=[f"batch-naive-commit notes={len(moves)}"],
    )


async def run_batch(
    *,
    source: Path,
    adapter_dir: Path,
    vault_root: Path,
    workers: int | None,
    batch_size: int | None,
    dry_run: bool,
    skip_consolidator: bool = False,
    timeout_seconds: float = 300.0,
) -> BatchRunResult:
    vault_root = vault_root.expanduser().resolve()
    adapter_dir = adapter_dir.expanduser().resolve()
    source = source.expanduser().resolve()

    if not adapter_dir.is_dir():
        raise BatchError(f"adapter_dir {adapter_dir} is not a directory")
    manifest_path = adapter_dir / "manifest.yaml"
    prompt_path = adapter_dir / "prompt.md"
    if not manifest_path.exists():
        raise BatchError(f"adapter missing manifest.yaml: {adapter_dir}")
    manifest = parse_worker_manifest(manifest_path.read_text(encoding="utf-8"))
    adapter_prompt = prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else ""

    run_id = _new_run_id()
    run_dir = vault_root / ".rufino" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    _ensure_gitignore(vault_root)

    # STAGE
    staged = stage_corpus(source, run_dir)
    if not staged.groups:
        raise BatchError("corpus is empty after staging — nothing to process")

    # PLAN
    effective_batch_size = batch_size if batch_size is not None else manifest.batch_size
    plan = build_plan(
        staged, run_id=run_id, adapter_dir=str(adapter_dir),
        batch_size=effective_batch_size,
    )
    plan_path = run_dir / "plan.json"
    plan_path.write_text(plan.to_json(), encoding="utf-8")
    if dry_run:
        return BatchRunResult(
            run_id=run_id, dry_run=True,
            notes_total=sum(len(w.notes) for w in plan.workers),
            plan_path=plan_path, commit_skipped=True,
        )

    # DISPATCH
    vault_slug = compute_vault_slug(vault_root)
    concepts_top = _gather_concepts_top_n(vault_root)
    effective_workers = workers if workers is not None else min(4, max(1, len(plan.workers)))

    def _prompt_for(assignment):
        staging_dir = run_dir / "workers" / assignment.worker_id
        return build_worker_system_prompt(
            manifest=manifest, adapter_prompt_text=adapter_prompt,
            assignment=assignment, vault_slug=vault_slug,
            staging_dir=staging_dir, vault_concepts_top_n=concepts_top,
            run_id=run_id,
        )

    await dispatch(
        plan=plan, run_dir=run_dir,
        system_prompt_for=_prompt_for, vault_slug=vault_slug,
        max_workers=effective_workers, timeout_seconds=timeout_seconds,
    )

    # VALIDATE + RETRY
    all_passed = []
    all_failed = []
    for assignment in plan.workers:
        staging_dir = run_dir / "workers" / assignment.worker_id
        report = validate_worker_output(staging_dir, manifest)
        if report.failed:
            retry_report = await retry_failed(
                failed=report.failed, manifest=manifest,
                adapter_prompt_text=adapter_prompt,
                worker_assignment=assignment, run_dir=run_dir,
                vault_slug=vault_slug, max_retries=2,
                timeout_seconds=timeout_seconds,
            )
            all_passed.extend(report.passed)
            all_passed.extend(retry_report.passed)
            all_failed.extend(retry_report.failed)
        else:
            all_passed.extend(report.passed)

    # Q&A collection
    pendings = collect_pending(run_dir)
    if pendings:
        write_questions_to_vault(pendings, vault_root)

    # CONSOLIDATE (or naive fallback)
    if skip_consolidator:
        plan_obj = _naive_commit_plan(
            run_dir, tuple(all_passed), manifest.destination_path,
        )
    else:
        try:
            plan_obj = await run_consolidator(
                run_dir=run_dir, vault_slug=vault_slug, timeout_seconds=600.0,
            )
        except Exception:
            plan_obj = None
        if plan_obj is None:
            plan_obj = _naive_commit_plan(
                run_dir, tuple(all_passed), manifest.destination_path,
            )

    # COMMIT
    tx = TransactionLog(run_dir / "commit.tx.json")
    commit(plan=plan_obj, vault_root=vault_root, run_dir=run_dir, tx_log=tx)

    summary = {
        "run_id": run_id,
        "notes_total": sum(len(w.notes) for w in plan.workers),
        "notes_ok": len(all_passed),
        "notes_failed": len(all_failed),
        "notes_pending_qa": len(pendings),
    }
    (run_dir / "run.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    return BatchRunResult(
        run_id=run_id, dry_run=False,
        notes_total=summary["notes_total"], notes_ok=summary["notes_ok"],
        notes_failed=summary["notes_failed"],
        notes_pending_qa=summary["notes_pending_qa"],
        plan_path=plan_path,
    )
