from pathlib import Path

import yaml
import pytest

from rufino.runtime.transaction_log import TransactionLog
from rufino.wizard.adapter_materializers.ingest import materialize_ingest
from rufino.wizard.spec_schema import IngestSpec


def _spec(**overrides) -> IngestSpec:
    base = dict(
        adapter_name="drive-facultad",
        source_name="gdrive",
        output_mode="import_raw",
        schedule="*/30 * * * *",
        auth={"type": "oauth2", "keychain_service": "rufino-gdrive"},
        target_inbox="inbox/cufona/",
        process_with="apunte-clase",
        trigger="immediate",
    )
    base.update(overrides)
    return IngestSpec(**base)


def test_materialize_ingest_creates_manifest(tmp_path: Path) -> None:
    log = TransactionLog(tmp_path / "tx.json")
    out = materialize_ingest(
        spec=_spec(),
        base_dir=tmp_path / "rufino",
        vault_slug="facultad",
        tx_log=log,
    )
    assert (out / "manifest.yaml").exists()
    parsed = yaml.safe_load((out / "manifest.yaml").read_text(encoding="utf-8"))
    assert parsed["adapter_name"] == "drive-facultad"
    assert parsed["source_name"] == "gdrive"
    assert parsed["output_mode"] == "import_raw"
    assert parsed["target_inbox"] == "inbox/cufona/"


def test_materialize_ingest_path_layout(tmp_path: Path) -> None:
    log = TransactionLog(tmp_path / "tx.json")
    out = materialize_ingest(
        spec=_spec(),
        base_dir=tmp_path / "rufino",
        vault_slug="facultad",
        tx_log=log,
    )
    expected = tmp_path / "rufino" / "adapters" / "ingest" / "facultad" / "drive-facultad"
    assert out == expected
    assert out.is_dir()


def test_materialize_ingest_rollback_restores_clean_state(tmp_path: Path) -> None:
    log = TransactionLog(tmp_path / "tx.json")
    out = materialize_ingest(
        spec=_spec(),
        base_dir=tmp_path / "rufino",
        vault_slug="facultad",
        tx_log=log,
    )
    assert out.exists()
    log.rollback()
    assert not out.exists()


def test_materialize_ingest_allows_null_schedule(tmp_path: Path) -> None:
    """On-demand ingests have no schedule. The materializer writes
    `schedule: null` so the manifest parser's required-field check is
    satisfied without forcing a cron."""
    spec = _spec(schedule=None)
    log = TransactionLog(tmp_path / "tx.json")
    out = materialize_ingest(
        spec=spec,
        base_dir=tmp_path / "rufino",
        vault_slug="facultad",
        tx_log=log,
    )
    parsed = yaml.safe_load((out / "manifest.yaml").read_text(encoding="utf-8"))
    assert "schedule" in parsed
    assert parsed["schedule"] is None


def test_materialize_ingest_invalid_manifest_raises(tmp_path: Path) -> None:
    """A semantically broken spec must trip the engine parser via the
    materializer's validation pass. We bypass spec_schema here to construct
    an IngestSpec with an output_mode the manifest parser does not accept."""
    spec = IngestSpec(
        adapter_name="x",
        source_name="x",
        output_mode="bogus_mode",
        schedule="* * * * *",
        auth={},
    )
    log = TransactionLog(tmp_path / "tx.json")
    with pytest.raises(ValueError, match="output_mode"):
        materialize_ingest(
            spec=spec,
            base_dir=tmp_path / "rufino",
            vault_slug="facultad",
            tx_log=log,
        )
