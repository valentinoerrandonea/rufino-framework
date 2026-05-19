"""emit_augmented: dispatch already-augmented records straight to Process (light).

emit_augmented is Ingest's third output mode (alongside emit_fact and
import_raw). Records returned by the fetcher are already augmented externally
(e.g. an upstream service has tagged/structured them), so they skip the inbox
+ LLM-augmentation step and go directly to a Process adapter in ``mode="light"``
which only refreshes the tag index and the processing log.
"""
import logging
from pathlib import Path
from typing import Iterable

from rufino.engine.ingest.cursor import CursorStore
from rufino.engine.ingest.fetcher_loader import load_fetcher
from rufino.engine.ingest.manifest import IngestAdapterManifest

logger = logging.getLogger(__name__)


def dispatch_to_process(
    *,
    record: dict,
    vault_root: Path,
    staging_dir: Path,
) -> dict:
    """Send a single record directly to a Process adapter, bypassing inbox.

    Writes the record to ``staging_dir/<id>.md`` and calls ``process_note`` in
    light mode. If processing raises, the staged file is moved under
    ``staging_dir/failed/`` so the operator can inspect it later.
    """
    from rufino.engine.process.dispatcher import process_note

    staging_dir.mkdir(parents=True, exist_ok=True)
    note_path = staging_dir / f"{record.get('id', 'unknown')}.md"
    note_path.write_text(record.get("content") or str(record), encoding="utf-8")
    try:
        result = process_note(note_path=note_path, vault_root=vault_root, mode="light")
        return {"status": "ok", "message": result.message}
    except Exception as e:  # noqa: BLE001 — plan specifies bare Exception capture
        failed = staging_dir / "failed"
        # TODO(v0.3): staging_dir/failed/ is append-only; needs retention policy.
        failed.mkdir(exist_ok=True)
        note_path.rename(failed / note_path.name)
        logger.error(
            "emit_augmented Process failed for %s: %s", record.get("id"), e
        )
        return {"status": "failed", "error": str(e)}


def run_emit_augmented(
    *,
    adapter_dir: Path,
    manifest: IngestAdapterManifest,
    vault_root: Path,
    rufino_state_dir: Path,
):
    """Iterate the fetcher and dispatch each record to Process (light).

    Returns an ``IngestResult`` (imported lazily to avoid a circular import
    with ``runner.py``).
    """
    # Local import to break the runner ⇄ emit_augmented circular dep.
    from rufino.engine.ingest.runner import IngestResult, _now_iso_utc

    if manifest.process_inline_with:
        logger.info(
            "emit_augmented[%s]: process_inline_with=%s is parsed but ignored in v0.2; "
            "records pass through mode='light' (tags + processing-log only).",
            manifest.adapter_name, manifest.process_inline_with,
        )

    fetcher = load_fetcher(adapter_dir)
    cursors = CursorStore(rufino_state_dir / "cursors.json")

    since = cursors.get(manifest.adapter_name)
    records: Iterable[dict] = fetcher(since=since)

    staging_dir = rufino_state_dir / "emit_augmented" / manifest.adapter_name

    emitted = 0
    errors: list[str] = []

    for record in records:
        outcome = dispatch_to_process(
            record=record,
            vault_root=vault_root,
            staging_dir=staging_dir,
        )
        if outcome["status"] == "ok":
            emitted += 1
        else:
            errors.append(
                f"{record.get('id', 'unknown')}: {outcome.get('error', 'unknown error')}"
            )

    # Only advance the cursor on a clean batch — consistent with _run_emit_fact.
    if not errors:
        cursors.set(manifest.adapter_name, _now_iso_utc())

    return IngestResult(
        adapter_name=manifest.adapter_name,
        facts_emitted=emitted,
        facts_skipped=0,
        errors=errors,
    )
