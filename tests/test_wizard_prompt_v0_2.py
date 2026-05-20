"""Regression guards on the v0.2 prompt updates: the wizard must instruct
Claude to emit `prompt_instructions` per processing adapter, `template_body`
per output adapter, decide on the embedder, and offer to load an initial
corpus after materialize."""
from rufino.wizard.system_prompt_assembler import build_system_prompt


def test_prompt_mentions_prompt_instructions_for_processing():
    prompt = build_system_prompt()
    assert "prompt_instructions" in prompt


def test_prompt_mentions_template_body_for_outputs():
    prompt = build_system_prompt()
    assert "template_body" in prompt


def test_prompt_asks_about_embeddings():
    prompt = build_system_prompt()
    lowered = prompt.lower()
    assert "embeddings" in lowered
    # The wizard plumbs the embeddings decision via post-materialize
    # `rufino enable-embeddings`, not via a `--embeddings` flag on
    # `rufino materialize` (which does not exist).
    assert "enable-embeddings" in prompt
    assert "detect-embeddings" in prompt


def test_prompt_asks_about_initial_corpus():
    prompt = build_system_prompt().lower()
    assert "corpus" in prompt
    assert "process-batch" in prompt


def test_prompt_lists_operative_rules_9_through_12():
    rules = build_system_prompt()
    # Anchor on the rule numbers introduced in v0.2 so future edits don't
    # silently delete them without updating this guard.
    for n in (9, 10, 11, 12):
        assert f"{n}." in rules, f"operative rule {n} missing"


def test_checklist_mentions_v0_2_items():
    prompt = build_system_prompt().lower()
    assert "prompt_instructions" in prompt or "prompt instructions" in prompt
    assert "template_body" in prompt or "template body" in prompt
    assert "corpus" in prompt
