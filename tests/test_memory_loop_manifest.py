import pytest
from rufino.engine.memory_loop.manifest import (
    MemoryLoopManifest,
    parse_manifest,
    ManifestParseError,
)


VALID_YAML = """
adapter_name: memory-loop-facultad
vertical_name: facultad

entity_types: [apunte_clase, materia, profesor, paper, tp, examen]

note_destinations:
  apunte_clase: "apuntes/<materia>/<YYYY-MM-DD>-<slug>.md"
  paper: "papers/<materia>/<slug>.md"

rule_extensions:
  - ./rules/facultad-vocabulary.md
  - ./rules/facultad-conventions.md
"""


def test_parses_full_manifest():
    m = parse_manifest(VALID_YAML)
    assert m.adapter_name == "memory-loop-facultad"
    assert m.vertical_name == "facultad"
    assert "apunte_clase" in m.entity_types
    assert m.note_destinations["paper"] == "papers/<materia>/<slug>.md"
    assert m.rule_extensions == (
        "./rules/facultad-vocabulary.md",
        "./rules/facultad-conventions.md",
    )


def test_missing_required_field_raises():
    yaml = "vertical_name: facultad\n"
    with pytest.raises(ManifestParseError, match="adapter_name"):
        parse_manifest(yaml)


def test_empty_entity_types_raises():
    yaml = """
adapter_name: x
vertical_name: y
entity_types: []
note_destinations: {}
"""
    with pytest.raises(ManifestParseError, match="entity_types"):
        parse_manifest(yaml)


def test_destinations_must_be_relative_paths():
    yaml = """
adapter_name: x
vertical_name: y
entity_types: [a]
note_destinations:
  a: "/absolute/path.md"
"""
    with pytest.raises(ManifestParseError, match="absolute path"):
        parse_manifest(yaml)
