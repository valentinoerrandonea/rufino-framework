import json

import pytest

from rufino.wizard.spec_schema import SpecError, WizardSpec, validate_spec


# Schema-valid minimal fixture. Mirrors the v0.2 strict shape — each Ingest /
# Process / Output entry carries the fields the materializer needs to write
# adapters end-to-end (manifest + prompt + template).
VALID_SPEC = {
    "vertical_name": "facultad",
    "patterns": ["long_documents_extraction", "person_centric_tracking"],
    "entities": ["apunte_clase", "materia", "profesor"],
    "sources": [
        {
            "adapter_name": "drive-pdfs",
            "source_name": "gdrive",
            "output_mode": "import_raw",
            "schedule": None,
            "auth": {"type": "none"},
            "target_inbox": "inbox/cufona/",
            "process_with": "apunte-clase",
            "trigger": "immediate",
        },
    ],
    "processing": [
        {
            "adapter_name": "apunte-clase",
            "note_type": "apunte_clase",
            "applies_when": {"source_dir": "inbox/"},
            "llm": "sonnet",
            "output_schema": {"required": {"title": "string"}, "optional": {}},
            "triple_vocabulary": ["tema-de"],
            "tag_axes": [{"axis": "materia", "format": "materia/<slug>"}],
            "destination_path": "apuntes/{slug}.md",
            "qa_triggers": [],
            "context_injectors": [],
            "batch_size": 10,
            "prompt_instructions": "# Procesá apuntes\n",
        },
    ],
    "outputs": [
        {
            "adapter_name": "digest-semanal",
            "trigger": {"type": "cron", "expression": "0 18 * * 5"},
            "query": [{"name": "all", "expression": "tag:apunte"}],
            "delivery": [{"channel": "file", "path": "digests/{date}.md"}],
            "template_body": "# Digest semanal\n",
        },
    ],
    "vocabulary": {
        "apunte_clase": "apuntes/<materia>/<YYYY-MM-DD>-<slug>.md",
        "materia": "materias/<slug>.md",
        "profesor": "profesores/<slug>.md",
    },
}


def test_validate_spec_accepts_valid():
    spec = validate_spec(VALID_SPEC)
    assert isinstance(spec, WizardSpec)
    assert spec.vertical_name == "facultad"
    assert len(spec.entities) == 3


def test_validate_spec_rejects_missing_field():
    bad = dict(VALID_SPEC)
    del bad["vertical_name"]
    with pytest.raises(SpecError, match="vertical_name"):
        validate_spec(bad)


def test_validate_spec_rejects_unknown_pattern():
    bad = dict(VALID_SPEC)
    bad["patterns"] = ["nonexistent_pattern"]
    with pytest.raises(SpecError, match="pattern"):
        validate_spec(bad)


def test_spec_can_load_from_json():
    spec_json = json.dumps(VALID_SPEC)
    spec = validate_spec(json.loads(spec_json))
    assert spec.vertical_name == "facultad"


@pytest.mark.parametrize("bad_vertical", [
    "",
    "../escape",
    "Has Spaces",
    "UPPERCASE",
    "starts_with_underscore",
    "1starts-with-digit",
    "a/b",
    "x" * 65,
])
def test_validate_spec_rejects_bad_vertical_name(bad_vertical):
    bad = dict(VALID_SPEC)
    bad["vertical_name"] = bad_vertical
    with pytest.raises(SpecError, match="vertical_name"):
        validate_spec(bad)


@pytest.mark.parametrize("bad_path", [
    "../../etc/passwd",
    "/absolute/path.md",
    "a/../b.md",
    "subdir/../../escape.md",
])
def test_validate_spec_rejects_vocabulary_path_traversal(bad_path):
    bad = dict(VALID_SPEC)
    bad["vocabulary"] = {"apunte_clase": bad_path}
    bad["entities"] = ["apunte_clase"]
    with pytest.raises(SpecError, match="vocabulary"):
        validate_spec(bad)


@pytest.mark.parametrize("field", ["entities", "sources", "processing", "outputs"])
def test_validate_spec_rejects_non_list_collections(field):
    bad = dict(VALID_SPEC)
    bad[field] = "not-a-list"
    with pytest.raises(SpecError, match=field):
        validate_spec(bad)


def test_spec_is_deeply_immutable():
    spec = validate_spec(VALID_SPEC)
    # sources[0] is now a frozen IngestSpec dataclass — attribute assignment fails.
    with pytest.raises((TypeError, AttributeError)):
        spec.sources[0].adapter_name = "pwned"  # type: ignore[misc]
    with pytest.raises((TypeError, AttributeError)):
        spec.vocabulary["apunte_clase"] = "pwned"  # type: ignore[index]


def test_spec_blocks_nested_dict_mutation():
    """Nested mappings inside typed specs (e.g. auth) are frozen recursively."""
    spec = validate_spec(VALID_SPEC)
    with pytest.raises((TypeError, AttributeError)):
        spec.sources[0].auth["type"] = "pwned"  # type: ignore[index]


@pytest.mark.parametrize("bad_entity", [
    "Has Spaces",
    "back`tick",
    "bra[cket]",
    "with\nnewline",
    "1starts-with-digit",
    "",
    "x" * 65,
    "with/slash",
])
def test_validate_spec_rejects_bad_entity_names(bad_entity):
    bad = dict(VALID_SPEC)
    bad["entities"] = [bad_entity]
    bad["vocabulary"] = {bad_entity: "ok/<slug>.md"}
    with pytest.raises(SpecError, match="entit"):
        validate_spec(bad)


def test_validate_spec_accepts_entity_with_underscore():
    spec = validate_spec({
        **VALID_SPEC,
        "entities": ["apunte_clase", "materia"],
        "vocabulary": {
            "apunte_clase": "apuntes/<slug>.md",
            "materia": "materias/<slug>.md",
        },
    })
    assert "apunte_clase" in spec.entities


def test_validate_spec_rejects_vocabulary_key_not_in_entities():
    bad = dict(VALID_SPEC)
    bad["vocabulary"] = {
        **VALID_SPEC["vocabulary"],
        "ghost": "ghost/<slug>.md",  # not in entities
    }
    with pytest.raises(SpecError, match="ghost"):
        validate_spec(bad)


def test_validate_spec_rejects_invalid_vocabulary_key_chars():
    bad = dict(VALID_SPEC)
    bad["entities"] = list(VALID_SPEC["entities"]) + ["with space"]
    # entities check would already reject this — assert it raises in entities path.
    with pytest.raises(SpecError):
        validate_spec(bad)


def test_validate_spec_rejects_vocabulary_key_with_uppercase_when_entity_valid():
    """If a vocabulary key carries uppercase, validate_spec must reject it
    (either in the entities check or in the vocabulary key check)."""
    bad = dict(VALID_SPEC)
    bad["vocabulary"] = {
        **VALID_SPEC["vocabulary"],
        "BadKey": "x/<slug>.md",
    }
    bad["entities"] = list(VALID_SPEC["entities"]) + ["BadKey"]
    with pytest.raises(SpecError):
        validate_spec(bad)
