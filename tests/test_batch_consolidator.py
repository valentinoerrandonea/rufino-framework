import json
from pathlib import Path

import pytest

from rufino.engine.process.batch.consolidator import (
    AuthorWrite,
    ConceptWrite,
    ConsolidationPlan,
    Move,
    TagIndexUpdate,
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
    assert parsed.moves == (Move(from_="workers/w/augmented/a.md", to="x/a.md"),)


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
    assert plan.author_writes[0].path == "autores/porter.md"
    assert isinstance(plan.author_writes[0], AuthorWrite)


def test_plan_defaults_author_writes_to_empty_when_missing():
    """Backward compat: plans v0.2.x without author_writes parse to empty."""
    raw = {
        "moves": [],
        "concept_writes": [],
        "tag_index_updates": [],
        "log_entries": [],
    }
    plan = validate_consolidation_plan(raw)
    assert plan.author_writes == ()


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


def test_author_write_rejects_path_outside_autores():
    with pytest.raises(ValueError, match="under autores"):
        AuthorWrite(path="apuntes/x.md", content="X")


def test_author_write_rejects_non_md_extension():
    with pytest.raises(ValueError, match="under autores"):
        AuthorWrite(path="autores/porter.txt", content="X")


def test_author_write_rejects_empty_content():
    with pytest.raises(ValueError, match="non-empty"):
        AuthorWrite(path="autores/porter.md", content="   \n")


def test_concept_write_rejects_path_outside_conceptos():
    with pytest.raises(ValueError, match="under conceptos"):
        ConceptWrite(path="apuntes/dfs.md", content="X")


def test_concept_write_rejects_empty_content():
    with pytest.raises(ValueError, match="non-empty"):
        ConceptWrite(path="conceptos/dfs.md", content="")


def test_move_rejects_empty_paths():
    with pytest.raises(ValueError):
        Move(from_="", to="x")
    with pytest.raises(ValueError):
        Move(from_="x", to="")


def test_tag_index_update_rejects_non_string_notes():
    with pytest.raises(ValueError):
        TagIndexUpdate(tag="materia/math", notes=("n1", 42))


def test_consolidation_plan_accepts_typed_objects_directly():
    plan = ConsolidationPlan(
        moves=(Move(from_="workers/w/augmented/a.md", to="apuntes/a.md"),),
        log_entries=("ok",),
    )
    assert plan.moves[0].from_ == "workers/w/augmented/a.md"
    assert plan.log_entries == ("ok",)


def test_preamble_specifies_author_note_required_sections():
    """Stricter assertion: the structural requirements (Bio / Obra principal /
    Por qué importa) must appear together, not just individually."""
    prompt = build_consolidator_system_prompt(
        run_dir=Path("/run"), vault_slug="test",
    )
    for needle in ("Bio:", "Obra principal:", "Por qué importa:"):
        assert needle in prompt, f"preamble missing author section {needle!r}"


def test_move_rejects_identical_from_and_to():
    with pytest.raises(ValueError, match="identical"):
        Move(from_="x", to="x")


def test_author_write_rejects_dot_segments():
    with pytest.raises(ValueError, match="'.' or '..'"):
        AuthorWrite(path="autores/./porter.md", content="X")
    with pytest.raises(ValueError, match="'.' or '..'"):
        AuthorWrite(path="autores/sub/../porter.md", content="X")


def test_concept_write_rejects_dot_segments():
    with pytest.raises(ValueError, match="'.' or '..'"):
        ConceptWrite(path="conceptos/sub/../dfs.md", content="X")


def test_validate_plan_wraps_dataclass_value_error_as_consolidation_error():
    """A path-outside-autores in the wire format must surface as
    ConsolidationError (so the runner's narrow `except` catches it and
    falls back to naive) — not as a bare ValueError."""
    raw = {
        "moves": [],
        "concept_writes": [],
        "author_writes": [{"path": "apuntes/x.md", "content": "X"}],
        "tag_index_updates": [],
        "log_entries": [],
    }
    with pytest.raises(ConsolidationError, match="invalid consolidation plan"):
        validate_consolidation_plan(raw)


def test_parser_rejects_unknown_concept_write_keys():
    """A typo like `Path` vs `path` (or a future schema-drift field) is
    surfaced loudly instead of being silently dropped."""
    raw = {
        "moves": [],
        "concept_writes": [
            {"path": "conceptos/x.md", "content": "X", "extra_unknown": 1},
        ],
        "tag_index_updates": [],
        "log_entries": [],
    }
    with pytest.raises(ConsolidationError, match="unknown keys"):
        validate_consolidation_plan(raw)


def test_parser_rejects_unknown_move_keys():
    raw = {
        "moves": [{"from": "a", "to": "b", "extra": "bad"}],
        "concept_writes": [],
        "tag_index_updates": [],
        "log_entries": [],
    }
    with pytest.raises(ConsolidationError, match="unknown keys"):
        validate_consolidation_plan(raw)


def test_preamble_concept_body_lists_all_five_sections():
    """Concept body schema requires all five marker sections — keyword-only
    matching (from the original test) lets a regression keep one keyword
    while gutting the others."""
    prompt = build_consolidator_system_prompt(
        run_dir=Path("/run"), vault_slug="test",
    )
    for needle in (
        "**Definición:",
        "**Contexto:",
        "**Ejemplo:",
        "**Relacionado con:",
        "**Formulado por:",
    ):
        assert needle in prompt, f"preamble missing concept section {needle!r}"
