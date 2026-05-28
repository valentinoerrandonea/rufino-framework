import pytest
from rufino.engine.process.manifest import (
    WorkerAdapterManifest,
    parse_worker_manifest,
    ManifestParseError,
)


VALID = """
adapter_name: apunte-clase
note_type: apunte_clase
applies_when:
  source_dir: rufino/inbox/
  matches_pattern: ["*.pdf", "*.md", "*.txt"]
llm: sonnet
mode_default: full
output_schema:
  required:
    materia: { type: enum_dynamic, source: "tags: materia/" }
    fecha_clase: date
    topics: list[str]
  optional:
    profesor: persona_ref
triple_vocabulary: [tema-de, expuesto-por, extiende]
tag_axes:
  - { axis: materia, format: "materia/<slug>", required: true }
  - { axis: tema, format: "tema/<slug>", min: 1 }
destination_path: "apuntes/{materia}/{fecha_clase}-{slug}.md"
qa_triggers:
  - { name: materia_ambigua, condition: "match_count(materia) >= 2" }
context_injectors:
  - { name: apuntes_previos, query: "tag=materia/<materia>, last 10 by date" }
"""


def test_parses_full_worker_manifest():
    m = parse_worker_manifest(VALID)
    assert m.adapter_name == "apunte-clase"
    assert m.note_type == "apunte_clase"
    assert m.llm == "sonnet"
    assert m.mode_default == "full"
    assert "tema-de" in m.triple_vocabulary
    assert m.destination_path == "apuntes/{materia}/{fecha_clase}-{slug}.md"
    assert m.qa_triggers[0]["name"] == "materia_ambigua"


def test_missing_required_fields_raise():
    with pytest.raises(ManifestParseError, match="adapter_name"):
        parse_worker_manifest("note_type: x\n")


def test_invalid_mode_default_raises():
    yaml = VALID.replace("mode_default: full", "mode_default: bogus")
    with pytest.raises(ManifestParseError, match="mode_default"):
        parse_worker_manifest(yaml)


def test_destination_must_be_relative():
    yaml = VALID.replace(
        'destination_path: "apuntes/{materia}/{fecha_clase}-{slug}.md"',
        'destination_path: "/abs/path.md"',
    )
    with pytest.raises(ManifestParseError, match="absolute"):
        parse_worker_manifest(yaml)


def test_manifest_dict_fields_are_immutable():
    m = parse_worker_manifest(VALID)
    with pytest.raises(TypeError):
        m.applies_when["injected"] = "evil"
    with pytest.raises(TypeError):
        m.output_schema["required"]["injected"] = "evil"


def test_manifest_defaults_compression_floor_to_none():
    m = parse_worker_manifest(VALID)
    assert m.compression_floor is None


def test_manifest_accepts_compression_floor_in_range():
    yaml = VALID + "\ncompression_floor: 0.9\n"
    m = parse_worker_manifest(yaml)
    assert m.compression_floor == 0.9


def test_manifest_accepts_compression_floor_zero_and_one():
    for value in (0.0, 1.0):
        yaml = VALID + f"\ncompression_floor: {value}\n"
        assert parse_worker_manifest(yaml).compression_floor == value


def test_manifest_coerces_int_compression_floor_to_float():
    yaml = VALID + "\ncompression_floor: 1\n"
    m = parse_worker_manifest(yaml)
    assert isinstance(m.compression_floor, float)
    assert m.compression_floor == 1.0


@pytest.mark.parametrize("value", ["1.5", "-0.1", "2"])
def test_manifest_rejects_compression_floor_out_of_range(value):
    yaml = VALID + f"\ncompression_floor: {value}\n"
    with pytest.raises(ManifestParseError, match=r"\[0\.0, 1\.0\]"):
        parse_worker_manifest(yaml)


def test_manifest_rejects_compression_floor_bool():
    """bool is an int subclass in Python; without the explicit guard a YAML
    'true' would silently coerce to 1.0."""
    yaml = VALID + "\ncompression_floor: true\n"
    with pytest.raises(ManifestParseError, match="must be a number"):
        parse_worker_manifest(yaml)


def test_manifest_rejects_compression_floor_string():
    yaml = VALID + "\ncompression_floor: \"0.9\"\n"
    with pytest.raises(ManifestParseError, match="must be a number"):
        parse_worker_manifest(yaml)


def test_manifest_construction_rejects_compression_floor_out_of_range():
    """Direct dataclass construction must also enforce the invariant — not
    only the YAML parser."""
    yaml = VALID
    base = parse_worker_manifest(yaml)
    kwargs = {
        f: getattr(base, f) for f in (
            "adapter_name", "note_type", "applies_when", "llm", "mode_default",
            "output_schema", "triple_vocabulary", "tag_axes", "destination_path",
            "qa_triggers", "context_injectors", "transform_hook", "batch_size",
        )
    }
    with pytest.raises(ValueError, match=r"\[0\.0, 1\.0\]"):
        WorkerAdapterManifest(**kwargs, compression_floor=1.5)
