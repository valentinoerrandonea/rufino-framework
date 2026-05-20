from pathlib import Path
from types import MappingProxyType

import yaml

from rufino.runtime.transaction_log import TransactionLog
from rufino.wizard.adapter_materializers.process import materialize_process
from rufino.wizard.spec_schema import ProcessSpec


def _make_spec(**overrides) -> ProcessSpec:
    base = dict(
        adapter_name="study",
        note_type="apunte",
        applies_when=MappingProxyType({"source_dir": "inbox/"}),
        llm="sonnet",
        output_schema=MappingProxyType(
            {"required": {"materia": {"type": "string"}}}
        ),
        triple_vocabulary=("pertenece-a-materia",),
        tag_axes=(),
        destination_path="apuntes/{materia}/{slug}.md",
        qa_triggers=(),
        context_injectors=(),
        batch_size=3,
        prompt_instructions="reescribí preservando fidelidad",
    )
    base.update(overrides)
    return ProcessSpec(**base)


def test_materializer_writes_compression_floor_when_set(tmp_path: Path):
    tx = TransactionLog(tmp_path / "tx.json")
    spec = _make_spec(compression_floor=0.9)
    adapter_dir = materialize_process(
        spec=spec, base_dir=tmp_path, vault_slug="test", tx_log=tx,
    )
    manifest = yaml.safe_load((adapter_dir / "manifest.yaml").read_text())
    assert manifest["compression_floor"] == 0.9


def test_materializer_omits_compression_floor_when_none(tmp_path: Path):
    tx = TransactionLog(tmp_path / "tx.json")
    spec = _make_spec(compression_floor=None)
    adapter_dir = materialize_process(
        spec=spec, base_dir=tmp_path, vault_slug="test", tx_log=tx,
    )
    manifest = yaml.safe_load((adapter_dir / "manifest.yaml").read_text())
    assert "compression_floor" not in manifest
