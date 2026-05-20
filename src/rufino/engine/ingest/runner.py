import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import yaml

from rufino.engine._transform_hook_invoker import _maybe_apply_transform_hook
from rufino.engine.ingest.manifest import parse_ingest_manifest, IngestAdapterManifest
from rufino.engine.ingest.cursor import CursorStore
from rufino.engine.ingest.dedup import DedupStore
from rufino.engine.ingest.fact_schema import validate_fact, FactSchemaError
from rufino.engine.ingest.fetcher_loader import load_fetcher


ProcessHook = Callable[[Path, Path, str], None]


class IngestPathError(Exception):
    """Raised when an adapter tries to write outside the vault root."""


@dataclass
class IngestResult:
    adapter_name: str
    facts_emitted: int
    facts_skipped: int
    errors: list[str]


def run_ingest(
    *,
    adapter_dir: Path,
    vault_root: Path,
    rufino_state_dir: Path,
    process_hook: ProcessHook | None = None,
) -> IngestResult:
    """Run an Ingest adapter. Dispatches to mode-specific subroutine."""
    manifest = parse_ingest_manifest(
        (adapter_dir / "manifest.yaml").read_text(encoding="utf-8")
    )

    if manifest.output_mode == "emit_fact":
        return _run_emit_fact(
            adapter_dir=adapter_dir,
            manifest=manifest,
            vault_root=vault_root,
            rufino_state_dir=rufino_state_dir,
        )
    if manifest.output_mode == "import_raw":
        return _run_import_raw(
            adapter_dir=adapter_dir,
            manifest=manifest,
            vault_root=vault_root,
            rufino_state_dir=rufino_state_dir,
            process_hook=process_hook,
        )
    if manifest.output_mode == "emit_augmented":
        # Lazy import: emit_augmented imports IngestResult/_now_iso_utc back from here.
        from rufino.engine.ingest.emit_augmented import run_emit_augmented
        return run_emit_augmented(
            adapter_dir=adapter_dir,
            manifest=manifest,
            vault_root=vault_root,
            rufino_state_dir=rufino_state_dir,
        )
    raise NotImplementedError(f"output_mode {manifest.output_mode} not implemented")


def _render_dest(template: str, *, fact: dict, today: str) -> str:
    return (
        template
        .replace("<YYYY-MM-DD>", today)
        .replace("<id>", str(fact["id"]))
    )


def _safe_join(vault_root: Path, relative: str) -> Path:
    """Resolve `relative` under `vault_root`, refusing path traversal."""
    target = (vault_root / relative).resolve()
    root = vault_root.resolve()
    if not target.is_relative_to(root):
        raise IngestPathError(f"Path escapes vault: {relative!r}")
    return target


def _now_iso_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _serialize_fact_md(*, source: str, fact_id: str, fact: dict) -> str:
    """YAML-frontmatter only note body. Uses yaml.safe_dump to handle any value safely."""
    frontmatter = {"source": source, "fact_id": fact_id, **fact}
    dumped = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True)
    return f"---\n{dumped}---\n"


def _run_emit_fact(
    *, adapter_dir: Path, manifest: IngestAdapterManifest, vault_root: Path, rufino_state_dir: Path,
) -> IngestResult:
    fetcher = load_fetcher(adapter_dir)
    cursors = CursorStore(rufino_state_dir / "cursors.json")
    dedup = DedupStore(rufino_state_dir / "dedup.sqlite")

    since = cursors.get(manifest.adapter_name)
    facts = fetcher(since=since)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    emitted = 0
    skipped = 0
    errors: list[str] = []

    hook_path = Path(manifest.transform_hook) if manifest.transform_hook else None

    for fact in facts:
        try:
            validate_fact(fact, schema=manifest.fact_schema)
        except FactSchemaError as e:
            errors.append(f"schema violation: {e}")
            continue

        fact = _maybe_apply_transform_hook(
            hook_path, fact, adapter_dir=adapter_dir,
        )

        fact_id = fact[manifest.dedup_by]
        if not dedup.is_new(source=manifest.source_name, fact_id=fact_id):
            skipped += 1
            continue

        try:
            fact_path = _safe_join(
                vault_root, _render_dest(manifest.destination_facts, fact=fact, today=today)
            )
        except IngestPathError as e:
            errors.append(str(e))
            continue

        fact_path.parent.mkdir(parents=True, exist_ok=True)
        fact_md = _serialize_fact_md(source=manifest.source_name, fact_id=fact_id, fact=fact)
        try:
            fact_path.write_text(fact_md, encoding="utf-8")
            if manifest.destination_raw:
                try:
                    raw_path = _safe_join(
                        vault_root,
                        _render_dest(manifest.destination_raw, fact=fact, today=today),
                    )
                except IngestPathError as e:
                    errors.append(str(e))
                    # fact_path written; mark seen so we don't re-emit. User
                    # must fix destination_raw manually.
                    dedup.mark_seen(source=manifest.source_name, fact_id=fact_id)
                    continue
                raw_path.parent.mkdir(parents=True, exist_ok=True)
                raw_path.write_text(json.dumps(fact, indent=2), encoding="utf-8")
        except OSError as e:
            errors.append(f"write failed for {fact_id}: {e}")
            # Mark seen so we don't loop on the same broken write every run.
            dedup.mark_seen(source=manifest.source_name, fact_id=fact_id)
            continue

        # write-then-mark: a crash here re-emits on next run (overwrites same path).
        # The reverse (mark first) would silently drop the fact.
        dedup.mark_seen(source=manifest.source_name, fact_id=fact_id)
        emitted += 1

    # Only advance cursor when the batch was clean — otherwise a failed fact
    # whose timestamp is past `since` would be unrecoverable.
    if not errors:
        cursors.set(manifest.adapter_name, _now_iso_utc())

    return IngestResult(
        adapter_name=manifest.adapter_name,
        facts_emitted=emitted,
        facts_skipped=skipped,
        errors=errors,
    )


def _run_import_raw(
    *,
    adapter_dir: Path,
    manifest: IngestAdapterManifest,
    vault_root: Path,
    rufino_state_dir: Path,
    process_hook: ProcessHook | None,
) -> IngestResult:
    fetcher = load_fetcher(adapter_dir)
    cursors = CursorStore(rufino_state_dir / "cursors.json")

    since = cursors.get(manifest.adapter_name)
    items = fetcher(since=since)

    inbox = (vault_root / manifest.target_inbox).resolve()
    if not inbox.is_relative_to(vault_root.resolve()):
        raise IngestPathError(f"target_inbox escapes vault: {manifest.target_inbox!r}")
    inbox.mkdir(parents=True, exist_ok=True)
    emitted = 0
    errors: list[str] = []

    hook_path = Path(manifest.transform_hook) if manifest.transform_hook else None

    for item in items:
        item = _maybe_apply_transform_hook(
            hook_path, item, adapter_dir=adapter_dir,
        )
        try:
            target = _safe_join(inbox, item["filename"])
        except IngestPathError as e:
            errors.append(str(e))
            continue
        target.write_text(item["content"], encoding="utf-8")
        emitted += 1
        if manifest.trigger == "immediate" and process_hook is not None:
            process_hook(target, vault_root, manifest.process_with)

    if not errors:
        cursors.set(manifest.adapter_name, _now_iso_utc())
    return IngestResult(
        adapter_name=manifest.adapter_name,
        facts_emitted=emitted,
        facts_skipped=0,
        errors=errors,
    )
