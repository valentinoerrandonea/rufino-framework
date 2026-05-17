import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from rufino.engine.ingest.manifest import parse_ingest_manifest
from rufino.engine.ingest.cursor import CursorStore
from rufino.engine.ingest.dedup import DedupStore
from rufino.engine.ingest.fact_schema import validate_fact, FactSchemaError
from rufino.engine.ingest.fetcher_loader import load_fetcher


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
    process_hook=None,
) -> IngestResult:
    """Run an Ingest adapter. Dispatches to mode-specific subroutine."""
    manifest = parse_ingest_manifest((adapter_dir / "manifest.yaml").read_text())

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
    raise NotImplementedError(f"output_mode {manifest.output_mode} not implemented")


def _render_dest(template: str, *, fact: dict, today: str) -> str:
    return (
        template
        .replace("<YYYY-MM-DD>", today)
        .replace("<id>", fact["id"])
    )


def _run_emit_fact(
    *, adapter_dir: Path, manifest, vault_root: Path, rufino_state_dir: Path,
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

    for fact in facts:
        try:
            validate_fact(fact, schema=manifest.fact_schema)
        except FactSchemaError as e:
            errors.append(f"schema violation: {e}")
            continue

        fact_id = fact[manifest.dedup_by]
        if not dedup.is_new(source=manifest.source_name, fact_id=fact_id):
            skipped += 1
            continue

        fact_path = vault_root / _render_dest(manifest.destination_facts, fact=fact, today=today)
        raw_path = vault_root / _render_dest(manifest.destination_raw, fact=fact, today=today)

        fact_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.parent.mkdir(parents=True, exist_ok=True)

        fact_md = (
            f"---\nsource: {manifest.source_name}\nfact_id: {fact_id}\n"
            + "\n".join(f"{k}: {v!r}" for k, v in fact.items())
            + "\n---\n"
        )
        fact_path.write_text(fact_md)
        raw_path.write_text(json.dumps(fact, indent=2))

        dedup.mark_seen(source=manifest.source_name, fact_id=fact_id)
        emitted += 1

    cursors.set(manifest.adapter_name, datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))

    return IngestResult(
        adapter_name=manifest.adapter_name,
        facts_emitted=emitted,
        facts_skipped=skipped,
        errors=errors,
    )


def _run_import_raw(
    *, adapter_dir: Path, manifest, vault_root: Path, rufino_state_dir: Path, process_hook,
) -> IngestResult:
    fetcher = load_fetcher(adapter_dir)
    cursors = CursorStore(rufino_state_dir / "cursors.json")

    since = cursors.get(manifest.adapter_name)
    items = fetcher(since=since)

    inbox = vault_root / manifest.target_inbox
    inbox.mkdir(parents=True, exist_ok=True)
    emitted = 0

    for item in items:
        target = inbox / item["filename"]
        target.write_text(item["content"])
        emitted += 1
        if manifest.trigger == "immediate" and process_hook is not None:
            process_hook(target, vault_root, manifest.process_with)

    cursors.set(manifest.adapter_name, datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    return IngestResult(
        adapter_name=manifest.adapter_name,
        facts_emitted=emitted,
        facts_skipped=0,
        errors=[],
    )
