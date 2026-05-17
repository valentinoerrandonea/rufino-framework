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


def test_run_works_through_apply_context_injectors(tmp_vault: Path):
    """QueryLayer.run is the drop-in replacement for StubQueryLayer.

    Validates behavior, not just type shape: feeds the real injector
    pipeline so a renamed method or wrong return type breaks the test.
    """
    from rufino.engine.process.context_injectors import apply_context_injectors

    (tmp_vault / "hit.md").write_text("regresion logistica")
    ql = QueryLayer(vault_root=tmp_vault, embedder=FakeEmbeddings())
    ql.rebuild_indices()

    context = apply_context_injectors(
        injectors=[{"name": "matches", "query": "<term>"}],
        variables={"term": "regresion"},
        query=ql,
    )
    assert "hit.md" in context["matches"]
