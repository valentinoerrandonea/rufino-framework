from pathlib import Path

import yaml
import pytest

from rufino.runtime.transaction_log import TransactionLog
from rufino.wizard.adapter_materializers.output import materialize_output
from rufino.wizard.spec_schema import OutputSpec


def _spec(**overrides) -> OutputSpec:
    base = dict(
        adapter_name="digest-semanal",
        trigger={"type": "cron", "expression": "0 9 * * 1"},
        query=(
            {"name": "decisiones", "expression": "tag:decision created:>7d"},
        ),
        delivery=({"channel": "file", "path": "reports/digest-semanal.md"},),
        template_body="# Digest semanal\n\n{% for d in decisiones %}- {{ d.title }}\n{% endfor %}\n",
    )
    base.update(overrides)
    return OutputSpec(**base)


def test_materialize_output_writes_manifest_and_template(tmp_path: Path) -> None:
    log = TransactionLog(tmp_path / "tx.json")
    out = materialize_output(
        spec=_spec(),
        base_dir=tmp_path / "rufino",
        vault_slug="facultad",
        tx_log=log,
    )
    manifest = out / "manifest.yaml"
    template = out / "template.md"
    assert manifest.exists()
    assert template.exists()
    parsed = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    assert parsed["adapter_name"] == "digest-semanal"
    assert parsed["trigger"] == {"type": "cron", "expression": "0 9 * * 1"}
    assert parsed["template"] == "template.md"
    assert template.read_text(encoding="utf-8").startswith("# Digest semanal")


def test_materialize_output_path_layout(tmp_path: Path) -> None:
    log = TransactionLog(tmp_path / "tx.json")
    out = materialize_output(
        spec=_spec(),
        base_dir=tmp_path / "rufino",
        vault_slug="facultad",
        tx_log=log,
    )
    expected = tmp_path / "rufino" / "adapters" / "output" / "facultad" / "digest-semanal"
    assert out == expected


def test_materialize_output_rollback(tmp_path: Path) -> None:
    log = TransactionLog(tmp_path / "tx.json")
    out = materialize_output(
        spec=_spec(),
        base_dir=tmp_path / "rufino",
        vault_slug="facultad",
        tx_log=log,
    )
    assert (out / "template.md").exists()
    log.rollback()
    assert not out.exists()


def test_materialize_output_event_trigger(tmp_path: Path) -> None:
    spec = _spec(trigger={"type": "on_event", "event": "note_created"})
    log = TransactionLog(tmp_path / "tx.json")
    out = materialize_output(
        spec=spec,
        base_dir=tmp_path / "rufino",
        vault_slug="facultad",
        tx_log=log,
    )
    parsed = yaml.safe_load((out / "manifest.yaml").read_text(encoding="utf-8"))
    assert parsed["trigger"]["type"] == "on_event"
    assert parsed["trigger"]["event"] == "note_created"


def test_materialize_output_invalid_trigger_raises(tmp_path: Path) -> None:
    spec = _spec(trigger={"type": "fantasia"})
    log = TransactionLog(tmp_path / "tx.json")
    with pytest.raises(ValueError, match="trigger"):
        materialize_output(
            spec=spec,
            base_dir=tmp_path / "rufino",
            vault_slug="facultad",
            tx_log=log,
        )
