"""Top-level orchestration for `rufino process-batch`.

Six stages: STAGE -> PLAN -> DISPATCH -> VALIDATE+RETRY -> Q&A collect ->
CONSOLIDATE (or naive fallback) -> COMMIT.
"""
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml

from rufino.engine._transform_hook_invoker import _maybe_apply_transform_hook
from rufino.engine.process.batch.committer import commit
from rufino.engine.process.batch.consolidator import (
    ConsolidationPlan,
    run_consolidator,
)
from rufino.engine.process.batch.dispatcher import dispatch
from rufino.engine.process.batch.errors import BatchError, ConsolidationError
from rufino.engine.process.batch.planner import build_plan
from rufino.engine.process.batch.qa_pending import (
    collect_pending,
    write_questions_to_vault,
)
from rufino.engine.process.batch.retry import retry_failed
from rufino.engine.process.batch.runner_helper import MAX_OUTPUT_BYTES
from rufino.engine.process.batch.stager import StagedCorpus, stage_corpus
from rufino.engine.process.batch.validator import (
    NoteValidation,
    check_compression_ratio,
    validate_worker_output,
)
from rufino.engine.process.batch.worker_prompt import (
    build_worker_system_prompt,
)
from rufino.engine.process.helpers.frontmatter import FrontmatterError, parse_frontmatter
from rufino.engine.process.manifest import WorkerAdapterManifest, parse_worker_manifest
from rufino.runtime.transaction_log import TransactionLog
from rufino.runtime.vault_lock import VaultLockedError, vault_lock
from rufino.runtime.vault_slug import compute_vault_slug


log = logging.getLogger(__name__)


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
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    return f"{ts}-{uuid.uuid4().hex[:6]}"


def _concepts_head_alphabetical(vault_root: Path, n: int = 30) -> list[str]:
    """First N concept slugs ordered alphabetically.

    Not a relevance ranking — concepts in the alphabetical tail are invisible
    to the worker. Acceptable for v0.1; revisit when the worker prompt needs
    actual top-K-by-relevance.
    """
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
    tmp = gi.parent / (gi.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(gi)


def _find_staged_input(staged: StagedCorpus, slug: str) -> Path | None:
    """Locate the staged input file whose stem matches the given slug.

    Returns None when the slug was minted from a source that no longer maps
    cleanly to a staged file (e.g. derived names) — caller treats this as a
    silent skip for advisory checks.
    """
    for group_files in staged.groups.values():
        for p in group_files:
            if p.stem == slug:
                return p
    return None


def _coerce_tag_list(raw: object) -> list[str]:
    """Coerce an arbitrarily-shaped `tags` frontmatter value into a list of
    strings, dropping non-string entries. Guards against LLM output that emits
    a single tag as a YAML scalar (would otherwise iterate characters)."""
    if isinstance(raw, str):
        return [raw]
    if not isinstance(raw, list):
        return []
    return [t for t in raw if isinstance(t, str)]


def _apply_process_transform_hooks(
    passed: tuple[NoteValidation, ...] | list[NoteValidation],
    *,
    manifest: WorkerAdapterManifest,
    adapter_dir: Path,
) -> None:
    """Run ``manifest.transform_hook`` against each passed note's frontmatter.

    Called between VALIDATE and CONSOLIDATE. The hook sees the parsed
    frontmatter dict and may mutate it; the mutated dict is re-serialized
    back to the same augmented file in place. Body is preserved verbatim.

    Errors (frontmatter parse, hook failure) are logged and the note is left
    unchanged — per-note try/except so one bad note never aborts the run.

    Note: any non-JSON-native YAML scalars in the frontmatter (e.g.,
    ``datetime.date``, sets, tuples) become strings after the hook's JSON
    round-trip. This is intentional given the primitive's JSON contract.
    """
    if manifest.transform_hook is None:
        return
    hook_path = Path(manifest.transform_hook)
    for nv in passed:
        try:
            text = nv.augmented_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            log.warning(
                "transform_hook: cannot read %s, skipping: %s",
                nv.augmented_path, e,
            )
            continue
        # Defensive: validator should reject FM-less augmented files
        # upstream. If somehow one slips through, skip rather than
        # silently turning a no-FM note into a has-FM note.
        if not text.startswith("---\n"):
            continue
        try:
            fm, body = parse_frontmatter(text)
        except FrontmatterError as e:
            log.warning(
                "transform_hook: cannot parse %s, skipping: %s",
                nv.augmented_path, e,
            )
            continue
        new_fm = _maybe_apply_transform_hook(
            hook_path, dict(fm), adapter_dir=adapter_dir,
        )
        if new_fm is fm or new_fm == fm:
            # No change (hook missing, errored, or returned same content).
            continue
        try:
            dumped = yaml.safe_dump(
                new_fm, sort_keys=False, allow_unicode=True,
            )
            nv.augmented_path.write_text(
                f"---\n{dumped}---\n{body}", encoding="utf-8",
            )
        except (OSError, yaml.YAMLError) as e:
            log.warning(
                "transform_hook: cannot write back %s, leaving unchanged: %s",
                nv.augmented_path, e,
            )


def _naive_commit_plan(
    run_dir: Path,
    passed: tuple[NoteValidation, ...],
    destination_template: str,
) -> tuple[ConsolidationPlan, list[NoteValidation]]:
    """Build a commit plan in-process, without invoking an LLM consolidator.

    Returns ``(plan, dropped)`` where ``dropped`` lists validated notes that
    could not be placed (bad frontmatter, missing template variables, etc).
    The caller is expected to demote ``dropped`` into the failure bucket so
    the run summary reflects what actually landed.
    """
    moves: list[dict[str, str]] = []
    tag_map: dict[str, list[str]] = {}
    dropped: list[NoteValidation] = []
    for nv in passed:
        slug = nv.slug
        try:
            fm, _ = parse_frontmatter(nv.augmented_path.read_text(encoding="utf-8"))
        except FrontmatterError as e:
            log.warning("naive plan dropped %s: frontmatter parse error: %s", slug, e)
            dropped.append(NoteValidation(
                slug=nv.slug, augmented_path=nv.augmented_path,
                delta_path=nv.delta_path,
                errors=nv.errors + (f"naive_plan_drop: frontmatter: {e}",),
            ))
            continue
        variables = {k: v for k, v in fm.items() if isinstance(v, str)}
        variables.setdefault("slug", slug)
        try:
            dest_rel = destination_template.format(**variables)
        except KeyError as e:
            log.warning(
                "naive plan dropped %s: destination template missing key %s",
                slug, e,
            )
            dropped.append(NoteValidation(
                slug=nv.slug, augmented_path=nv.augmented_path,
                delta_path=nv.delta_path,
                errors=nv.errors + (f"naive_plan_drop: missing template key {e}",),
            ))
            continue
        rel_from = nv.augmented_path.relative_to(run_dir)
        moves.append({"from": str(rel_from), "to": dest_rel})
        for tag in _coerce_tag_list(fm.get("tags")):
            tag_map.setdefault(tag, []).append(slug)
    plan = ConsolidationPlan(
        moves=moves, concept_writes=[], author_writes=[],
        tag_index_updates=[{"tag": t, "notes": ns} for t, ns in tag_map.items()],
        log_entries=[f"batch-naive-commit notes={len(moves)} dropped={len(dropped)}"],
    )
    return plan, dropped


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
    multimodal: bool = False,
) -> BatchRunResult:
    vault_root = vault_root.expanduser().resolve()
    adapter_dir = adapter_dir.expanduser().resolve()
    source = source.expanduser().resolve()

    try:
        with vault_lock(vault_root, wait=False):
            return await _run_batch_locked(
                source=source, adapter_dir=adapter_dir, vault_root=vault_root,
                workers=workers, batch_size=batch_size, dry_run=dry_run,
                skip_consolidator=skip_consolidator,
                timeout_seconds=timeout_seconds,
                multimodal=multimodal,
            )
    except VaultLockedError as e:
        raise BatchError(str(e)) from e


async def _run_batch_locked(
    *,
    source: Path,
    adapter_dir: Path,
    vault_root: Path,
    workers: int | None,
    batch_size: int | None,
    dry_run: bool,
    skip_consolidator: bool,
    timeout_seconds: float,
    multimodal: bool = False,
) -> BatchRunResult:
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
    log.info("run_id=%s adapter=%s vault=%s", run_id, adapter_dir.name, vault_root)

    # STAGE
    staged = stage_corpus(source, run_dir, multimodal=multimodal)
    if not staged.groups:
        raise BatchError("corpus is empty after staging — nothing to process")
    log.info(
        "STAGE done groups=%d skipped=%d multimodal=%s",
        len(staged.groups), len(staged.skipped), multimodal,
    )

    # PLAN
    effective_batch_size = batch_size if batch_size is not None else manifest.batch_size
    plan = build_plan(
        staged, run_id=run_id, adapter_dir=str(adapter_dir),
        batch_size=effective_batch_size,
    )
    plan_path = run_dir / "plan.json"
    plan_path.write_text(plan.to_json(), encoding="utf-8")
    notes_total = sum(len(w.notes) for w in plan.workers)
    log.info("PLAN workers=%d notes_total=%d", len(plan.workers), notes_total)
    if dry_run:
        return BatchRunResult(
            run_id=run_id, dry_run=True,
            notes_total=notes_total,
            plan_path=plan_path, commit_skipped=True,
        )

    # DISPATCH
    vault_slug = compute_vault_slug(vault_root)
    concepts_head = _concepts_head_alphabetical(vault_root)
    effective_workers = workers if workers is not None else min(4, max(1, len(plan.workers)))

    def _prompt_for(assignment):
        staging_dir = run_dir / "workers" / assignment.worker_id
        return build_worker_system_prompt(
            manifest=manifest, adapter_prompt_text=adapter_prompt,
            assignment=assignment, vault_slug=vault_slug,
            staging_dir=staging_dir, vault_concepts_top_n=concepts_head,
            run_id=run_id,
        )

    outcome = await dispatch(
        plan=plan, run_dir=run_dir,
        system_prompt_for=_prompt_for, vault_slug=vault_slug,
        max_workers=effective_workers, timeout_seconds=timeout_seconds,
    )
    log.info("DISPATCH done max_workers=%d", effective_workers)
    if outcome.truncated_count:
        log.warning(
            "DISPATCH truncated_workers=%d cap=%d bytes "
            "(revisar logs si el output incompleto causó fallos downstream)",
            outcome.truncated_count, MAX_OUTPUT_BYTES,
        )

    # VALIDATE + RETRY
    all_passed: list[NoteValidation] = []
    all_failed: list[NoteValidation] = []
    for assignment in plan.workers:
        staging_dir = run_dir / "workers" / assignment.worker_id
        report = validate_worker_output(staging_dir, manifest, assignment=assignment)
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
    log.info("VALIDATE done passed=%d failed=%d", len(all_passed), len(all_failed))

    # Compression floor check (advisory, v0.3 — logs a warning per note that
    # falls below the floor; does NOT mark them as failed).
    if manifest.compression_floor is not None:
        for nv in all_passed:
            staged_path = _find_staged_input(staged, nv.slug)
            if staged_path is None:
                continue
            check_compression_ratio(
                original=staged_path,
                augmented=nv.augmented_path,
                floor=manifest.compression_floor,
            )

    # TRANSFORM HOOK — mutate passed notes' frontmatter in place. Misbehaving
    # hooks degrade gracefully (logged warning) so a single bad hook can't
    # abort the run. Runs between VALIDATE and CONSOLIDATE so the
    # consolidator sees the post-hook frontmatter.
    _apply_process_transform_hooks(
        all_passed, manifest=manifest, adapter_dir=adapter_dir,
    )

    # Q&A collection
    pendings = collect_pending(run_dir)
    if pendings:
        write_questions_to_vault(pendings, vault_root)
        log.info("Q&A wrote %d pending question(s) to vault/questions/", len(pendings))

    # CONSOLIDATE (or naive fallback). Narrow except: only known recoverable
    # error class falls back; unknown errors propagate so bugs are loud.
    if skip_consolidator:
        plan_obj, naive_dropped = _naive_commit_plan(
            run_dir, tuple(all_passed), manifest.destination_path,
        )
        all_failed.extend(naive_dropped)
    else:
        try:
            plan_obj = await run_consolidator(
                run_dir=run_dir, vault_slug=vault_slug, timeout_seconds=600.0,
            )
        except ConsolidationError as e:
            log.warning("consolidator output unusable, falling back to naive: %s", e)
            plan_obj = None
        if plan_obj is None:
            plan_obj, naive_dropped = _naive_commit_plan(
                run_dir, tuple(all_passed), manifest.destination_path,
            )
            all_failed.extend(naive_dropped)
    log.info("CONSOLIDATE done moves=%d", len(plan_obj.moves))

    # COMMIT
    tx = TransactionLog(run_dir / "commit.tx.json")
    commit(plan=plan_obj, vault_root=vault_root, run_dir=run_dir, tx_log=tx)
    log.info("COMMIT done")

    notes_ok = len(plan_obj.moves)
    summary = {
        "run_id": run_id,
        "notes_total": notes_total,
        "notes_ok": notes_ok,
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
