from pathlib import Path

import yaml
import pytest

from rufino.runtime.transaction_log import TransactionLog
from rufino.wizard.adapter_materializers.process import materialize_process
from rufino.wizard.spec_schema import ProcessSpec


def _spec(**overrides) -> ProcessSpec:
    base = dict(
        adapter_name="apunte-clase",
        note_type="apunte_clase",
        applies_when={"source_dir": "inbox/cufona/"},
        llm="sonnet",
        output_schema={"required": {"title": "string"}, "optional": {}},
        triple_vocabulary=("tema-de", "fuente-de"),
        tag_axes=({"axis": "materia", "format": "materia/<slug>", "required": True, "min": 1},),
        destination_path="apuntes/{materia}/{slug}.md",
        qa_triggers=(),
        context_injectors=(),
        batch_size=10,
        prompt_instructions="# Procesá apuntes\n\nLeé la nota y extraé título + materia.\n",
    )
    base.update(overrides)
    return ProcessSpec(**base)


def test_materialize_process_writes_manifest_and_prompt(tmp_path: Path) -> None:
    log = TransactionLog(tmp_path / "tx.json")
    out = materialize_process(
        spec=_spec(),
        base_dir=tmp_path / "rufino",
        vault_slug="facultad",
        tx_log=log,
    )
    manifest = out / "manifest.yaml"
    prompt = out / "prompt.md"
    assert manifest.exists()
    assert prompt.exists()
    parsed = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    assert parsed["adapter_name"] == "apunte-clase"
    assert parsed["note_type"] == "apunte_clase"
    assert parsed["mode_default"] == "full"
    assert prompt.read_text(encoding="utf-8").startswith("# Procesá apuntes")


def test_materialize_process_path_layout(tmp_path: Path) -> None:
    log = TransactionLog(tmp_path / "tx.json")
    out = materialize_process(
        spec=_spec(),
        base_dir=tmp_path / "rufino",
        vault_slug="facultad",
        tx_log=log,
    )
    expected = tmp_path / "rufino" / "adapters" / "process" / "facultad" / "apunte-clase"
    assert out == expected


def test_materialize_process_rollback_removes_files(tmp_path: Path) -> None:
    log = TransactionLog(tmp_path / "tx.json")
    out = materialize_process(
        spec=_spec(),
        base_dir=tmp_path / "rufino",
        vault_slug="facultad",
        tx_log=log,
    )
    assert (out / "manifest.yaml").exists()
    assert (out / "prompt.md").exists()
    log.rollback()
    assert not out.exists()


def test_materialize_process_invalid_destination_path_raises(tmp_path: Path) -> None:
    spec = _spec(destination_path="/absoluto/no.md")
    log = TransactionLog(tmp_path / "tx.json")
    with pytest.raises(ValueError, match="destination_path"):
        materialize_process(
            spec=spec,
            base_dir=tmp_path / "rufino",
            vault_slug="facultad",
            tx_log=log,
        )
