"""End-to-end coverage that wizard-materialized emit_facts adapters round-trip
through the engine parser without breaking. Regression for review-claude C3 /
codex P0 #2 (wizard <-> engine manifest-shape mismatch)."""

from pathlib import Path

import pytest
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


def test_materialize_ingest_writes_fetcher_when_body_provided(tmp_path: Path) -> None:
    """F7 — si la spec incluye fetcher_body, se materializa fetcher.py con ese cuerpo."""
    spec_dict = _emit_facts_spec_dict()
    spec_dict["sources"][0]["fetcher_body"] = (
        "def fetch(cursor):\n"
        "    return [], cursor\n"
    )
    spec = validate_spec(spec_dict)
    tx = TransactionLog(tmp_path / "tx.json")
    adapter_dir = materialize_ingest(
        spec=spec.sources[0],
        base_dir=tmp_path / "h",
        vault_slug="demo",
        tx_log=tx,
    )
    fetcher = adapter_dir / "fetcher.py"
    assert fetcher.exists()
    assert "def fetch" in fetcher.read_text(encoding="utf-8")


def test_materialize_ingest_writes_scaffold_when_no_body(tmp_path: Path) -> None:
    """Si la spec no incluye fetcher_body, se materializa scaffold con NotImplementedError."""
    spec = validate_spec(_emit_facts_spec_dict())
    tx = TransactionLog(tmp_path / "tx.json")
    adapter_dir = materialize_ingest(
        spec=spec.sources[0],
        base_dir=tmp_path / "h",
        vault_slug="demo",
        tx_log=tx,
    )
    fetcher = adapter_dir / "fetcher.py"
    assert fetcher.exists()
    body = fetcher.read_text(encoding="utf-8")
    assert "TODO" in body
    assert "NotImplementedError" in body
    assert "def fetch" in body


def test_materialize_ingest_fetcher_rolls_back(tmp_path: Path) -> None:
    """fetcher.py debe registrarse en el tx_log para rollback completo."""
    spec = validate_spec(_emit_facts_spec_dict())
    tx = TransactionLog(tmp_path / "tx.json")
    adapter_dir = materialize_ingest(
        spec=spec.sources[0],
        base_dir=tmp_path / "h",
        vault_slug="demo",
        tx_log=tx,
    )
    assert (adapter_dir / "fetcher.py").exists()
    tx.rollback()
    assert not (adapter_dir / "fetcher.py").exists()
    assert not adapter_dir.exists()


def test_validate_spec_rejects_non_string_fetcher_body() -> None:
    """fetcher_body debe ser string si está presente."""
    from rufino.wizard.spec_schema import SpecError
    bad = _emit_facts_spec_dict()
    bad["sources"][0]["fetcher_body"] = 42
    with pytest.raises(SpecError, match="fetcher_body"):
        validate_spec(bad)


def test_materialize_ingest_writes_transform_when_body_provided(tmp_path: Path) -> None:
    """F8 — si la spec incluye transform_hook_body, se escribe transform.py + manifest field."""
    spec_dict = _emit_facts_spec_dict()
    spec_dict["sources"][0]["transform_hook_body"] = (
        "import json, sys\n"
        "rec = json.loads(sys.stdin.read())\n"
        "rec['extra'] = 'tagged'\n"
        "print(json.dumps(rec))\n"
    )
    spec = validate_spec(spec_dict)
    tx = TransactionLog(tmp_path / "tx.json")
    adapter_dir = materialize_ingest(
        spec=spec.sources[0], base_dir=tmp_path / "h",
        vault_slug="demo", tx_log=tx,
    )
    transform_path = adapter_dir / "transform.py"
    assert transform_path.exists()
    body = transform_path.read_text(encoding="utf-8")
    assert "rec['extra'] = 'tagged'" in body

    manifest = yaml.safe_load((adapter_dir / "manifest.yaml").read_text())
    assert manifest["transform_hook"] == "transform.py"


def test_materialize_ingest_omits_transform_when_no_body(tmp_path: Path) -> None:
    spec = validate_spec(_emit_facts_spec_dict())
    tx = TransactionLog(tmp_path / "tx.json")
    adapter_dir = materialize_ingest(
        spec=spec.sources[0], base_dir=tmp_path / "h",
        vault_slug="demo", tx_log=tx,
    )
    assert not (adapter_dir / "transform.py").exists()
    manifest = yaml.safe_load((adapter_dir / "manifest.yaml").read_text())
    assert "transform_hook" not in manifest or manifest.get("transform_hook") is None


def test_validate_spec_rejects_non_string_transform_hook_body() -> None:
    from rufino.wizard.spec_schema import SpecError
    bad = _emit_facts_spec_dict()
    bad["sources"][0]["transform_hook_body"] = 42
    with pytest.raises(SpecError, match="transform_hook_body"):
        validate_spec(bad)
