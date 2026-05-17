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
