import json

import pytest

from rufino.wizard.spec_schema import SpecError, WizardSpec, validate_spec


VALID_SPEC = {
    "vertical_name": "facultad",
    "patterns": ["long_documents_extraction", "person_centric_tracking"],
    "entities": ["apunte_clase", "materia", "profesor"],
    "sources": [
        {"adapter_name": "drive-pdfs", "output_mode": "import_raw"},
    ],
    "processing": [
        {"adapter_name": "apunte-clase", "note_type": "apunte_clase"},
    ],
    "outputs": [
        {"adapter_name": "digest-semanal", "cron": "0 18 * * 5"},
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
    with pytest.raises((TypeError, AttributeError)):
        spec.sources[0]["adapter_name"] = "pwned"  # type: ignore[index]
    with pytest.raises((TypeError, AttributeError)):
        spec.vocabulary["apunte_clase"] = "pwned"  # type: ignore[index]


def test_spec_blocks_nested_dict_mutation():
    nested_spec = validate_spec({
        **VALID_SPEC,
        "sources": [{"adapter_name": "drive-pdfs", "config": {"key": "v"}}],
    })
    with pytest.raises((TypeError, AttributeError)):
        nested_spec.sources[0]["config"]["key"] = "pwned"  # type: ignore[index]


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
