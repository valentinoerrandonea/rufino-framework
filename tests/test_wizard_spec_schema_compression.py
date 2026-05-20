import pytest

from rufino.wizard.spec_schema import SpecError, _validate_process


def _base_process_entry(**overrides):
    base = {
        "adapter_name": "study",
        "note_type": "apunte",
        "applies_when": {"source_dir": "inbox/"},
        "llm": "sonnet",
        "output_schema": {"required": {"materia": {"type": "string"}}},
        "triple_vocabulary": ["pertenece-a-materia"],
        "tag_axes": [],
        "destination_path": "apuntes/{materia}/{slug}.md",
        "qa_triggers": [],
        "context_injectors": [],
        "batch_size": 3,
        "prompt_instructions": "reescribí preservando fidelidad",
    }
    base.update(overrides)
    return base


def test_compression_floor_defaults_to_none():
    spec = _validate_process(_base_process_entry(), idx=0)
    assert spec.compression_floor is None


def test_compression_floor_accepts_valid_ratio():
    spec = _validate_process(
        _base_process_entry(compression_floor=0.9), idx=0,
    )
    assert spec.compression_floor == 0.9


def test_compression_floor_rejects_out_of_range():
    with pytest.raises(SpecError, match="compression_floor must be in"):
        _validate_process(
            _base_process_entry(compression_floor=1.5), idx=0,
        )


def test_compression_floor_rejects_non_numeric():
    with pytest.raises(SpecError, match="compression_floor must be a number"):
        _validate_process(
            _base_process_entry(compression_floor="0.9"), idx=0,
        )
