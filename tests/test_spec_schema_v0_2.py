"""v0.2 strict spec schema: IngestSpec/ProcessSpec/OutputSpec typed dataclasses
+ cross-ref validation between sources[].process_with and processing[].adapter_name."""
import pytest

from rufino.wizard.spec_schema import (
    IngestSpec,
    OutputSpec,
    ProcessSpec,
    SpecError,
    validate_spec,
)


def _base_raw() -> dict:
    return {
        "vertical_name": "facultad",
        "patterns": ["long_documents_extraction"],
        "entities": ["apunte_clase"],
        "vocabulary": {"apunte_clase": "apuntes/<materia>/<slug>.md"},
        "sources": [],
        "processing": [],
        "outputs": [],
    }


def _valid_process_dict(**overrides) -> dict:
    base = {
        "adapter_name": "apunte-clase",
        "note_type": "apunte_clase",
        "applies_when": {"source_dir": "inbox/"},
        "llm": "sonnet",
        "output_schema": {"required": {"title": "string"}, "optional": {}},
        "triple_vocabulary": ["tema-de"],
        "tag_axes": [{"axis": "materia", "format": "materia/<slug>", "required": True, "min": 1}],
        "destination_path": "apuntes/{materia}/{slug}.md",
        "qa_triggers": [],
        "context_injectors": [],
        "batch_size": 10,
        "prompt_instructions": "# Procesá apuntes\n",
    }
    base.update(overrides)
    return base


def test_validate_spec_accepts_typed_processing():
    raw = _base_raw()
    raw["processing"] = [_valid_process_dict()]
    spec = validate_spec(raw)
    assert isinstance(spec.processing[0], ProcessSpec)
    assert spec.processing[0].prompt_instructions.startswith("# Procesá")
    assert spec.processing[0].adapter_name == "apunte-clase"
    assert spec.processing[0].batch_size == 10


def test_validate_spec_rejects_processing_without_prompt_instructions():
    raw = _base_raw()
    pd = _valid_process_dict()
    del pd["prompt_instructions"]
    raw["processing"] = [pd]
    with pytest.raises(SpecError, match="prompt_instructions"):
        validate_spec(raw)


def test_validate_spec_rejects_cross_ref_missing_process():
    raw = _base_raw()
    raw["sources"] = [{
        "adapter_name": "x",
        "source_name": "x",
        "output_mode": "import_raw",
        "schedule": None,
        "auth": {"type": "none"},
        "target_inbox": "inbox/",
        "process_with": "no-existe",
        "trigger": "immediate",
    }]
    with pytest.raises(SpecError, match="process_with.*no-existe"):
        validate_spec(raw)


def test_validate_spec_rejects_cross_ref_process_inline_with_missing():
    raw = _base_raw()
    raw["sources"] = [{
        "adapter_name": "ig-emit",
        "source_name": "instagram",
        "output_mode": "emit_augmented",
        "schedule": None,
        "auth": {"type": "none"},
        "process_inline_with": "no-existe",
    }]
    with pytest.raises(SpecError, match="process_inline_with.*no-existe"):
        validate_spec(raw)


def test_validate_spec_accepts_cross_ref_resolved():
    raw = _base_raw()
    raw["sources"] = [{
        "adapter_name": "drive",
        "source_name": "gdrive",
        "output_mode": "import_raw",
        "schedule": None,
        "auth": {"type": "none"},
        "target_inbox": "inbox/",
        "process_with": "apunte-clase",
        "trigger": "immediate",
    }]
    raw["processing"] = [_valid_process_dict()]
    spec = validate_spec(raw)
    assert isinstance(spec.sources[0], IngestSpec)
    assert spec.sources[0].process_with == "apunte-clase"


def test_validate_spec_typed_output():
    raw = _base_raw()
    raw["outputs"] = [{
        "adapter_name": "digest-semanal",
        "trigger": {"type": "cron", "expression": "0 18 * * 5"},
        "query": [{"name": "all", "expression": "tag:apunte"}],
        "delivery": [{"channel": "file", "path": "digests/{date}.md"}],
        "template_body": "# Digest {{date}}\n",
    }]
    spec = validate_spec(raw)
    assert isinstance(spec.outputs[0], OutputSpec)
    assert spec.outputs[0].template_body.startswith("# Digest")


def test_validate_spec_rejects_output_without_template_body():
    raw = _base_raw()
    raw["outputs"] = [{
        "adapter_name": "digest-semanal",
        "trigger": {"type": "cron", "expression": "0 18 * * 5"},
        "query": [{"name": "all", "expression": "tag:apunte"}],
        "delivery": [{"channel": "file", "path": "digests/{date}.md"}],
    }]
    with pytest.raises(SpecError, match="template_body"):
        validate_spec(raw)


def test_validate_spec_rejects_ingest_unknown_output_mode():
    raw = _base_raw()
    raw["sources"] = [{
        "adapter_name": "x",
        "source_name": "x",
        "output_mode": "weird-thing",
        "schedule": None,
        "auth": {"type": "none"},
    }]
    with pytest.raises(SpecError, match="output_mode"):
        validate_spec(raw)
