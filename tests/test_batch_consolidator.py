import json
from pathlib import Path

import pytest

from rufino.engine.process.batch.consolidator import (
    ConsolidationPlan,
    build_consolidator_system_prompt,
    validate_consolidation_plan,
)
from rufino.engine.process.batch.errors import ConsolidationError


def test_validate_plan_accepts_complete():
    raw = {
        "moves": [{"from": "workers/w/augmented/a.md", "to": "x/a.md"}],
        "concept_writes": [],
        "tag_index_updates": [],
        "log_entries": ["ok"],
    }
    parsed = validate_consolidation_plan(raw)
    assert isinstance(parsed, ConsolidationPlan)
    assert parsed.moves == [{"from": "workers/w/augmented/a.md", "to": "x/a.md"}]


def test_validate_plan_rejects_missing_key():
    with pytest.raises(ConsolidationError):
        validate_consolidation_plan({"moves": []})


def test_validate_plan_rejects_bad_move():
    raw = {"moves": [{"from": "x"}], "concept_writes": [],
           "tag_index_updates": [], "log_entries": []}
    with pytest.raises(ConsolidationError, match="move"):
        validate_consolidation_plan(raw)


def test_build_prompt_mentions_run_dir_and_slug():
    prompt = build_consolidator_system_prompt(
        run_dir=Path("/run"), vault_slug="myslug",
    )
    assert "/run" in prompt
    assert "myslug" in prompt
    assert "consolidation-plan.json" in prompt


def test_preamble_mentions_author_writes():
    prompt = build_consolidator_system_prompt(
        run_dir=Path("/run"), vault_slug="test",
    )
    assert "author_writes" in prompt
    assert "autores/" in prompt


def test_preamble_asks_for_concept_body_enrichment():
    """Each concept body must call out Definicion / Contexto / Ejemplo /
    Relacionado / Formulado-por sections so the consolidator stops
    emitting empty concept stubs (Gap 2)."""
    prompt = build_consolidator_system_prompt(
        run_dir=Path("/run"), vault_slug="test",
    )
    for needle in ("Definici", "Contexto", "Ejemplo", "Relacionado", "Formulado"):
        assert needle in prompt, f"preamble missing {needle!r}"


def test_preamble_asks_consolidator_to_read_augmented_for_concept_bodies():
    prompt = build_consolidator_system_prompt(
        run_dir=Path("/run"), vault_slug="test",
    )
    assert "augmented" in prompt.lower()


def test_preamble_sets_author_threshold_at_two():
    """N>=2 explicit so the consolidator doesn't promote one-off lateral
    mentions to dedicated author notes."""
    prompt = build_consolidator_system_prompt(
        run_dir=Path("/run"), vault_slug="test",
    )
    assert "al menos 2" in prompt or ">= 2" in prompt or "≥ 2" in prompt


def test_preamble_forbids_placeholder_filler():
    """No 'Expandi con tu propia explicacion' style stubs — better an
    honest gap than fake content."""
    prompt = build_consolidator_system_prompt(
        run_dir=Path("/run"), vault_slug="test",
    )
    assert "placeholder" in prompt.lower() or "no escribas" in prompt.lower()


def test_validate_plan_rejects_concept_write_missing_content():
    raw = {
        "moves": [],
        "concept_writes": [{"path": "conceptos/x.md"}],
        "tag_index_updates": [],
        "log_entries": [],
    }
    with pytest.raises(ConsolidationError, match="concept_write"):
        validate_consolidation_plan(raw)


def test_validate_plan_rejects_tag_update_missing_notes():
    raw = {
        "moves": [],
        "concept_writes": [],
        "tag_index_updates": [{"tag": "x"}],
        "log_entries": [],
    }
    with pytest.raises(ConsolidationError, match="tag_index_update"):
        validate_consolidation_plan(raw)


def test_validate_plan_rejects_tag_update_notes_not_list():
    raw = {
        "moves": [],
        "concept_writes": [],
        "tag_index_updates": [{"tag": "x", "notes": "n"}],
        "log_entries": [],
    }
    with pytest.raises(ConsolidationError, match="tag_index_update"):
        validate_consolidation_plan(raw)


def test_plan_accepts_author_writes():
    raw = {
        "moves": [],
        "concept_writes": [],
        "author_writes": [
            {
                "path": "autores/porter.md",
                "content": (
                    "---\ntipo: persona\n---\n# Michael Porter\n\nBio.\n"
                ),
                "wins_over": [],
            },
        ],
        "tag_index_updates": [],
        "log_entries": [],
    }
    plan = validate_consolidation_plan(raw)
    assert len(plan.author_writes) == 1
    assert plan.author_writes[0]["path"] == "autores/porter.md"


def test_plan_defaults_author_writes_to_empty_when_missing():
    """Backward compat: plans v0.2.x without author_writes parse to empty."""
    raw = {
        "moves": [],
        "concept_writes": [],
        "tag_index_updates": [],
        "log_entries": [],
    }
    plan = validate_consolidation_plan(raw)
    assert plan.author_writes == []


def test_plan_rejects_author_write_missing_content():
    raw = {
        "moves": [],
        "concept_writes": [],
        "author_writes": [{"path": "autores/porter.md"}],
        "tag_index_updates": [],
        "log_entries": [],
    }
    with pytest.raises(ConsolidationError, match="author_write"):
        validate_consolidation_plan(raw)


def test_plan_rejects_author_writes_not_list():
    raw = {
        "moves": [],
        "concept_writes": [],
        "author_writes": "not-a-list",
        "tag_index_updates": [],
        "log_entries": [],
    }
    with pytest.raises(ConsolidationError, match="author_writes"):
        validate_consolidation_plan(raw)
