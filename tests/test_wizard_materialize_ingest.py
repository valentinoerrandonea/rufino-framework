"""End-to-end coverage that wizard-materialized emit_facts adapters round-trip
through the engine parser without breaking. Regression for review-claude C3 /
codex P0 #2 (wizard <-> engine manifest-shape mismatch)."""

from pathlib import Path

import yaml

from rufino.engine.ingest.manifest import parse_ingest_manifest
from rufino.runtime.transaction_log import TransactionLog
from rufino.wizard.adapter_materializers.ingest import materialize_ingest
from rufino.wizard.spec_schema import validate_spec


def _emit_facts_spec_dict() -> dict:
    return {
        "vertical_name": "demo",
        "patterns": ["discrete_events_with_metadata"],
        "entities": ["person"],
        "sources": [{
            "adapter_name": "drive-meet",
            "source_name": "google-drive",
            "output_mode": "emit_facts",
            "schedule": "*/15 * * * *",
            "auth": {"keychain_label": "x"},
            "emits": ["meeting"],
            "fact_schema": {"meeting": {"id": "str"}},
            "destination": {"facts": "_data/meetings.jsonl", "raw": "_data/raw.jsonl"},
            "dedup_by": "id",
        }],
        "processing": [],
        "outputs": [],
        "vocabulary": {"person": "personas/{name}.md"},
    }


def test_emit_facts_spec_round_trips_through_materializer(tmp_path: Path) -> None:
    """Regression: C3 — wizard emit_facts genera un manifest que el engine acepta."""
    spec = validate_spec(_emit_facts_spec_dict())
    tx = TransactionLog(tmp_path / "tx.json")
    adapter_dir = materialize_ingest(
        spec=spec.sources[0],
        base_dir=tmp_path / "rufino_home",
        vault_slug="demo",
        tx_log=tx,
    )
    yaml_text = (adapter_dir / "manifest.yaml").read_text(encoding="utf-8")
    manifest = parse_ingest_manifest(yaml_text)
    assert manifest.destination_facts == "_data/meetings.jsonl"
    assert manifest.destination_raw == "_data/raw.jsonl"
    assert manifest.dedup_by == "id"


def test_emit_facts_spec_without_raw_destination_is_valid(tmp_path: Path) -> None:
    """``destination.raw`` es opcional; sólo ``facts`` es requerido."""
    spec_dict = _emit_facts_spec_dict()
    spec_dict["sources"][0]["destination"] = {"facts": "_data/m.jsonl"}
    spec = validate_spec(spec_dict)
    tx = TransactionLog(tmp_path / "tx.json")
    adapter_dir = materialize_ingest(
        spec=spec.sources[0],
        base_dir=tmp_path / "rufino_home",
        vault_slug="demo",
        tx_log=tx,
    )
    manifest = parse_ingest_manifest((adapter_dir / "manifest.yaml").read_text())
    assert manifest.destination_facts == "_data/m.jsonl"
    assert manifest.destination_raw is None


def test_emit_facts_manifest_serializes_destination_as_mapping(tmp_path: Path) -> None:
    """El YAML escrito por el materializer debe tener destination como mapping."""
    spec = validate_spec(_emit_facts_spec_dict())
    tx = TransactionLog(tmp_path / "tx.json")
    adapter_dir = materialize_ingest(
        spec=spec.sources[0],
        base_dir=tmp_path / "rufino_home",
        vault_slug="demo",
        tx_log=tx,
    )
    raw = yaml.safe_load((adapter_dir / "manifest.yaml").read_text())
    assert isinstance(raw["destination"], dict)
    assert raw["destination"]["facts"] == "_data/meetings.jsonl"
    assert raw["dedup_by"] == "id"  # string, no list
