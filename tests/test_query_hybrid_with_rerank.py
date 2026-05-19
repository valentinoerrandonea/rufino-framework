from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from rufino.engine.query.api import QueryLayer
from rufino.engine.query.note_ref import NoteRef
from rufino.runtime.embedder.resolve import NoopEmbedder


def _make_layer(tmp_path: Path, embedder) -> QueryLayer:
    return QueryLayer(vault_root=tmp_path, embedder=embedder)


def test_hybrid_with_noop_embedder_raises_not_implemented(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("hola")
    ql = _make_layer(tmp_path, NoopEmbedder())
    with pytest.raises(NotImplementedError, match="enable-embeddings"):
        ql.search("hola", mode="hybrid")


def test_hybrid_uses_cross_encoder_to_rerank(tmp_path: Path) -> None:
    notes = {"a.md": "alpha content", "b.md": "beta content", "c.md": "gamma content"}
    for name, body in notes.items():
        (tmp_path / name).write_text(body, encoding="utf-8")

    fake_embedder = MagicMock()
    fake_embedder.embed = MagicMock(return_value=[0.0])
    ql = _make_layer(tmp_path, fake_embedder)

    lex = [NoteRef("a.md", score=1.0), NoteRef("b.md", score=0.9)]
    sem = [NoteRef("b.md", score=0.8), NoteRef("c.md", score=0.7)]

    rer = MagicMock()
    rer.rerank = MagicMock(side_effect=lambda q, cands: list(reversed(cands)))

    with patch.object(ql._lex, "search", return_value=lex), \
         patch.object(ql._sem, "search", return_value=sem), \
         patch(
             "rufino.engine.query.api.CrossEncoderReranker",
             return_value=rer,
         ):
        results = ql.search("anything", mode="hybrid", k=10)

    # Union (lex first, then sem) preserves order; reversed gives c, b, a.
    paths = [r.relative_path for r in results]
    assert paths == ["c.md", "b.md", "a.md"]
    assert rer.rerank.called
    # The rerank input is the note contents in the union order.
    call_args = rer.rerank.call_args
    assert call_args.args[0] == "anything"
    assert "alpha" in call_args.args[1][0]
    assert "beta" in call_args.args[1][1]
    assert "gamma" in call_args.args[1][2]


def test_hybrid_degrades_to_union_when_sentence_transformers_missing(
    tmp_path: Path, caplog
) -> None:
    """If the cross-encoder lib isn't importable, hybrid returns the union
    in lex+sem order (no rerank) and logs a warning instead of crashing."""
    import logging
    for name in ("a.md", "b.md"):
        (tmp_path / name).write_text("body", encoding="utf-8")

    fake_embedder = MagicMock()
    ql = _make_layer(tmp_path, fake_embedder)
    lex = [NoteRef("a.md")]
    sem = [NoteRef("b.md")]

    rer = MagicMock()
    rer.rerank = MagicMock(side_effect=ImportError("sentence_transformers"))

    with patch.object(ql._lex, "search", return_value=lex), \
         patch.object(ql._sem, "search", return_value=sem), \
         patch(
             "rufino.engine.query.api.CrossEncoderReranker",
             return_value=rer,
         ), caplog.at_level(logging.WARNING):
        results = ql.search("q", mode="hybrid", k=10)
    assert [r.relative_path for r in results] == ["a.md", "b.md"]
    assert "reranker unavailable" in caplog.text


def test_hybrid_truncates_to_k(tmp_path: Path) -> None:
    for i in range(5):
        (tmp_path / f"n{i}.md").write_text(f"body {i}", encoding="utf-8")

    fake_embedder = MagicMock()
    ql = _make_layer(tmp_path, fake_embedder)

    lex = [NoteRef(f"n{i}.md") for i in range(3)]
    sem = [NoteRef(f"n{i}.md") for i in range(3, 5)]
    rer = MagicMock()
    rer.rerank = MagicMock(side_effect=lambda q, cands: cands)

    with patch.object(ql._lex, "search", return_value=lex), \
         patch.object(ql._sem, "search", return_value=sem), \
         patch(
             "rufino.engine.query.api.CrossEncoderReranker",
             return_value=rer,
         ):
        results = ql.search("q", mode="hybrid", k=2)
    assert len(results) == 2
