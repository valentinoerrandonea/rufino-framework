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


def test_build_system_prompt_is_cached():
    """Same call returns identical object (no re-read of disk on each invocation)."""
    a = build_system_prompt()
    b = build_system_prompt()
    assert a is b


def test_prompt_instructs_to_ask_about_hooks():
    """Regression guard: the wizard must ask before installing Claude Code
    hooks (opt-in) and pass the matching flag to `rufino materialize`."""
    prompt = build_system_prompt()
    assert "--install-hooks" in prompt
    assert "--no-install-hooks" in prompt
    # The user-facing question and the checklist item both anchor the behavior.
    assert "captura" in prompt.lower() or "capturar" in prompt.lower()
    assert "opt-in" in prompt.lower()


def test_prompt_documents_processing_entry_required_fields():
    """Regression guard for the note_type=null bug: the wizard must be told
    the full shape of a processing[] entry, not just prompt_instructions.

    The WizardSpec schema requires note_type, applies_when, llm,
    output_schema, destination_path and batch_size on every processing
    entry. When the prompt omitted them, the wizard emitted `note_type: null`
    and `rufino materialize` failed validation. Keep the prompt and the
    schema in lockstep."""
    prompt = build_system_prompt()
    for field in (
        "note_type",
        "applies_when",
        "llm",
        "output_schema",
        "destination_path",
        "batch_size",
    ):
        assert field in prompt, f"processing[] field not documented: {field}"


def test_prompt_documents_top_level_spec_shape():
    """Second lockstep guard (surfaced by the v0.3.1 e2e): the prompt must
    pin the top-level spec shape, especially that `entities` is a list of
    plain strings (not {name, description} objects) and `vocabulary` is an
    entity->path mapping. When these were undocumented the wizard emitted
    entity objects and `rufino materialize` failed validation."""
    prompt = build_system_prompt()
    assert "Shape top-level de la spec" in prompt
    # entities-as-strings clarification (the actual failure mode)
    assert "entities" in prompt
    assert "NO objetos" in prompt or "no objetos" in prompt.lower()
    assert "vocabulary" in prompt


def test_prompt_clarifies_adapter_is_a_path():
    """The post-materialize process-batch guidance must show that --adapter
    is a path under ~/.rufino/adapters/process/<slug>/<name>, not a bare
    adapter name (which fails click's exists=True path check)."""
    prompt = build_system_prompt()
    assert ".rufino/adapters/process" in prompt
