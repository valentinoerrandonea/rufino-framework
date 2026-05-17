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
