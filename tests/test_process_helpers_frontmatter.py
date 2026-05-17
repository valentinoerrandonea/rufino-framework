import pytest
from rufino.engine.process.helpers.frontmatter import (
    parse_frontmatter,
    render_frontmatter,
    validate_against_schema,
    FrontmatterError,
)


def test_parse_roundtrip():
    note = "---\ntitle: hello\ntags: [a, b]\n---\nBody here.\n"
    fm, body = parse_frontmatter(note)
    assert fm == {"title": "hello", "tags": ["a", "b"]}
    assert body == "Body here.\n"


def test_parse_note_without_frontmatter():
    fm, body = parse_frontmatter("Just body.\n")
    assert fm == {}
    assert body == "Just body.\n"


def test_render_frontmatter():
    rendered = render_frontmatter({"a": 1, "tags": ["x"]}, "Body.\n")
    assert rendered.startswith("---\n")
    assert "a: 1" in rendered
    assert rendered.endswith("Body.\n")


def test_validate_schema_required_present():
    schema = {"required": {"materia": {"type": "string"}, "topics": "list[str]"}}
    fm = {"materia": "ml-i", "topics": ["a"]}
    validate_against_schema(fm, schema)  # no raise


def test_validate_schema_required_missing_raises():
    schema = {"required": {"materia": {"type": "string"}}}
    fm = {"other": "x"}
    with pytest.raises(FrontmatterError, match="materia"):
        validate_against_schema(fm, schema)


def test_validate_schema_optional_absent_ok():
    schema = {"required": {}, "optional": {"profesor": "persona_ref"}}
    validate_against_schema({}, schema)  # no raise
