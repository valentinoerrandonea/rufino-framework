from rufino.wizard.system_prompt_assembler import build_system_prompt


def test_includes_all_11_sections():
    prompt = build_system_prompt()
    expected_headers = [
        "Identidad y rol",
        "Lenguaje user-facing",
        "Conocimiento del runtime",
        "Patterns iniciales",
        "Reglas de traducción",
        "Reglas operativas",
        "Tracking de objetivos",
        "Output esperado",
        "Features distintivas",
        "Features opcionales",
        "Big bang",
    ]
    for h in expected_headers:
        assert h in prompt, f"Section header missing: {h}"


def test_embeds_pattern_files():
    prompt = build_system_prompt()
    assert "discrete_events_with_metadata" in prompt
    assert "Trigger language" in prompt


def test_embeds_language_rules():
    prompt = build_system_prompt()
    assert "manifest" in prompt
    assert "qué querés trackear" in prompt


def test_no_unfilled_jinja_placeholders():
    prompt = build_system_prompt()
    assert "{{" not in prompt
    assert "{%" not in prompt


def test_includes_all_six_patterns():
    prompt = build_system_prompt()
    for pattern_name in [
        "discrete_events_with_metadata",
        "long_documents_extraction",
        "person_centric_tracking",
        "decision_log_with_rationale",
        "temporal_self_observation",
        "knowledge_graph_projects",
    ]:
        assert pattern_name in prompt, f"Pattern missing: {pattern_name}"
