"""Retry loop for failed notes: re-invoke the worker for one note at a time,
with an appended RETRY block listing specific errors. After `max_retries`
fail, bounce the note to `failed/<slug>/`.
"""
import json
import os
import shutil
from pathlib import Path

from rufino.engine.process.batch.dispatcher import (
    SESSION_EXPIRED_EXIT_CODE,
    build_argv,
)
from rufino.engine.process.batch.errors import WorkerSessionExpiredError
from rufino.engine.process.batch.planner import WorkerAssignment
from rufino.engine.process.batch.runner_helper import run_claude
from rufino.engine.process.batch.validator import (
    NoteValidation,
    ValidationReport,
    _validate_one,
)
from rufino.engine.process.batch.worker_prompt import (
    build_retry_appendix,
    build_worker_system_prompt,
)
from rufino.engine.process.manifest import WorkerAdapterManifest


def _write_single_note_assignment(
    staging_dir: Path, *, run_id: str, worker_id: str, group: str, note_path: Path,
) -> None:
    payload = {
        "run_id": run_id,
        "worker_id": worker_id,
        "group": group,
        "notes": [str(note_path)],
    }
    staging_dir.mkdir(parents=True, exist_ok=True)
    (staging_dir / "assignment.json").write_text(json.dumps(payload, indent=2))


async def _retry_one(
    note_path: Path,
    *,
    base_prompt: str,
    appendix: str,
    staging_dir: Path,
    assignment: WorkerAssignment,
    run_id: str,
    vault_slug: str,
    timeout_seconds: float,
) -> None:
    _write_single_note_assignment(
        staging_dir,
        run_id=run_id, worker_id=assignment.worker_id, group=assignment.group,
        note_path=note_path,
    )
    argv = build_argv(
        system_prompt=base_prompt + appendix, vault_slug=vault_slug,
    )
    result = await run_claude(
        argv=argv, cwd=staging_dir, env=os.environ.copy(),
        timeout_seconds=timeout_seconds,
    )
    if result.exit_code == SESSION_EXPIRED_EXIT_CODE:
        raise WorkerSessionExpiredError(
            "Tu sesión Claude está expirada. Corré `claude login` y reintentá."
        )


def _bounce_to_failed(
    staging_dir: Path, slug: str, validation: NoteValidation,
) -> None:
    failed_dir = staging_dir / "failed" / slug
    failed_dir.mkdir(parents=True, exist_ok=True)
    aug = staging_dir / "augmented" / f"{slug}.md"
    delta = staging_dir / "deltas" / f"{slug}.json"
    if aug.exists():
        shutil.copy2(aug, failed_dir / "augmented.md")
        aug.unlink()
    if delta.exists():
        shutil.copy2(delta, failed_dir / "delta.json")
        delta.unlink()
    (failed_dir / "error.json").write_text(json.dumps({
        "slug": slug,
        "errors": list(validation.errors),
    }, indent=2))


async def retry_failed(
    *,
    failed: tuple[NoteValidation, ...],
    manifest: WorkerAdapterManifest,
    adapter_prompt_text: str,
    worker_assignment: WorkerAssignment,
    run_dir: Path,
    vault_slug: str,
    max_retries: int = 2,
    timeout_seconds: float = 300.0,
) -> ValidationReport:
    staging_dir = run_dir / "workers" / worker_assignment.worker_id
    base_prompt = build_worker_system_prompt(
        manifest=manifest, adapter_prompt_text=adapter_prompt_text,
        assignment=worker_assignment, vault_slug=vault_slug,
        staging_dir=staging_dir, vault_concepts_top_n=[],
        run_id=run_dir.name,
    )
    passed: list[NoteValidation] = []
    still_failed: list[NoteValidation] = []

    for nv in failed:
        matching = [p for p in worker_assignment.notes if p.stem == nv.slug]
        if not matching:
            still_failed.append(nv)
            _bounce_to_failed(staging_dir, nv.slug, nv)
            continue
        note_path = matching[0]
        current = nv
        won = False
        for _ in range(max_retries):
            appendix = build_retry_appendix(list(current.errors))
            await _retry_one(
                note_path, base_prompt=base_prompt, appendix=appendix,
                staging_dir=staging_dir, assignment=worker_assignment,
                run_id=run_dir.name, vault_slug=vault_slug,
                timeout_seconds=timeout_seconds,
            )
            aug = staging_dir / "augmented" / f"{nv.slug}.md"
            delta = staging_dir / "deltas" / f"{nv.slug}.json"
            if not aug.exists():
                continue
            current = _validate_one(aug, delta, manifest)
            if current.passed:
                passed.append(current)
                won = True
                break
        if not won:
            still_failed.append(current)
            _bounce_to_failed(staging_dir, nv.slug, current)

    return ValidationReport(passed=tuple(passed), failed=tuple(still_failed))
