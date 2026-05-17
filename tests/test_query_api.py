from pathlib import Path
import pytest

from rufino.engine.query.api import QueryLayer


class FakeEmbeddings:
    def embed(self, text: str) -> list[float]:
        import hashlib
        h = hashlib.sha256(text.encode()).digest()[:8]
        return [b / 255.0 for b in h]


def test_search_lexical_mode(tmp_vault: Path):
    (tmp_vault / "x.md").write_text("regresion logistica")
    ql = QueryLayer(vault_root=tmp_vault, embedder=FakeEmbeddings())
    ql.rebuild_indices()
    results = ql.search("regresion", mode="lexical")
    assert any(r.relative_path == "x.md" for r in results)


def test_search_semantic_mode(tmp_vault: Path):
    (tmp_vault / "x.md").write_text("svm")
    ql = QueryLayer(vault_root=tmp_vault, embedder=FakeEmbeddings())
    ql.rebuild_indices()
    results = ql.search("svm", mode="semantic")
    assert len(results) == 1


def test_traverse_via_graph(tmp_vault: Path):
    (tmp_vault / "c.md").write_text(
        "---\ntriples:\n  - { r: tema-de, o: ml-i }\n---\nbody\n"
    )
    ql = QueryLayer(vault_root=tmp_vault, embedder=FakeEmbeddings())
    ql.rebuild_indices()
    results = ql.traverse(node="ml-i", relation="tema-de", depth=1, reverse=True)
    assert any(r.relative_path == "c.md" for r in results)


def test_invalid_mode_raises(tmp_vault: Path):
    ql = QueryLayer(vault_root=tmp_vault, embedder=FakeEmbeddings())
    with pytest.raises(ValueError):
        ql.search("x", mode="bogus")


def test_run_matches_query_protocol(tmp_vault: Path):
    """QueryLayer.run is the drop-in replacement for StubQueryLayer."""
    from rufino.engine.process.context_injectors import QueryLayer as QueryProtocol

    (tmp_vault / "hit.md").write_text("regresion")
    ql = QueryLayer(vault_root=tmp_vault, embedder=FakeEmbeddings())
    ql.rebuild_indices()

    assert isinstance(ql.run("regresion"), list)
    assert all(isinstance(x, str) for x in ql.run("regresion"))
    # Structural Protocol compliance (no isinstance — runtime_checkable not declared)
    _: QueryProtocol = ql  # noqa: F841 — type-check only
