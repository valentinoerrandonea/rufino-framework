import pytest
from pathlib import Path
from rufino.engine.qa.template import (
    QuestionTemplate,
    parse_template_file,
    render_question,
    TemplateError,
)


FIXTURE = Path(__file__).parent / "fixtures" / "qa-templates" / "materia-ambigua.md"


def test_parses_template_metadata():
    t = parse_template_file(FIXTURE)
    assert t.template_name == "materia_ambigua"
    assert "apunte_slug" in t.required_context
    assert "enum_from" in t.expected_answer


def test_renders_with_full_context():
    t = parse_template_file(FIXTURE)
    rendered = render_question(t, context={
        "apunte_slug": "clase3",
        "candidate_materias": [
            {"slug": "ml-i", "confidence": 70, "reason": "menciona regresión"},
            {"slug": "stats-ii", "confidence": 60, "reason": "menciona inferencia"},
        ],
        "evidence": "fragmento del texto",
    })
    assert "clase3" in rendered
    assert "[[materia-ml-i]]" in rendered
    assert "70%" in rendered
    assert "fragmento del texto" in rendered


def test_render_with_missing_required_context_raises():
    t = parse_template_file(FIXTURE)
    with pytest.raises(TemplateError, match="apunte_slug"):
        render_question(t, context={})
