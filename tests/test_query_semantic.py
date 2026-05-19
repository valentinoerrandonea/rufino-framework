from pathlib import Path

import pytest

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


def test_semantic_rebuild_excludes_meta_and_dot_dirs(tmp_vault: Path):
    """Notes inside _meta/, .obsidian/, .git/ must not be indexed."""
    (tmp_vault / "real.md").write_text("user note")
    (tmp_vault / "_meta").mkdir()
    (tmp_vault / "_meta" / "system.md").write_text("system note")
    (tmp_vault / ".obsidian").mkdir()
    (tmp_vault / ".obsidian" / "tpl.md").write_text("template")

    backend = SemanticBackend(vault_root=tmp_vault, embedder=FakeEmbeddings())
    backend.rebuild_index()
    results = backend.search("anything", k=10)
    paths = sorted(r.relative_path for r in results)
    assert paths == ["real.md"]


def test_semantic_backend_does_not_create_sqlite_with_noop_embedder(tmp_vault: Path):
    """F12 — SemanticBackend con NoopEmbedder no debe crear _meta/embeddings.sqlite
    en __post_init__. Antes, el sqlite phantom se materializaba aunque el vault
    no usara embeddings."""
    from rufino.runtime.embedder.resolve import NoopEmbedder
    backend = SemanticBackend(vault_root=tmp_vault, embedder=NoopEmbedder())
    sqlite_path = tmp_vault / "_meta" / "embeddings.sqlite"
    assert not sqlite_path.exists(), (
        "NoopEmbedder no debe inicializar el sqlite — embeddings está disabled"
    )


def test_semantic_backend_creates_sqlite_lazily_with_real_embedder(tmp_vault: Path):
    """Con un embedder real, sqlite se crea en el primer rebuild (lazy)."""
    backend = SemanticBackend(vault_root=tmp_vault, embedder=FakeEmbeddings())
    (tmp_vault / "a.md").write_text("hola")
    backend.rebuild_index()
    sqlite_path = tmp_vault / "_meta" / "embeddings.sqlite"
    assert sqlite_path.exists()
