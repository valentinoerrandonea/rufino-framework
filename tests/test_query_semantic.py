from pathlib import Path
from rufino.engine.query.semantic import SemanticBackend


class FakeEmbeddings:
    """Deterministic fake embeddings: hash(text) → 8-dim vector."""
    def embed(self, text: str) -> list[float]:
        import hashlib
        h = hashlib.sha256(text.encode()).digest()[:8]
        return [b / 255.0 for b in h]


def test_index_and_search_with_fake_embeddings(tmp_vault: Path):
    (tmp_vault / "a.md").write_text("ml regression")
    (tmp_vault / "b.md").write_text("svm trees")

    backend = SemanticBackend(vault_root=tmp_vault, embedder=FakeEmbeddings())
    backend.rebuild_index()

    results = backend.search("ml regression", k=2)
    assert len(results) == 2
    paths = sorted(r.relative_path for r in results)
    assert "a.md" in paths
    assert "b.md" in paths


def test_empty_vault_returns_empty(tmp_vault: Path):
    backend = SemanticBackend(vault_root=tmp_vault, embedder=FakeEmbeddings())
    backend.rebuild_index()
    assert backend.search("anything", k=5) == []
