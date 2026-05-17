from pathlib import Path
from rufino.engine.query.graph import GraphBackend


def test_extracts_triples_from_frontmatter_and_traverses(tmp_vault: Path):
    (tmp_vault / "clase1.md").write_text(
        "---\ntriples:\n  - { r: tema-de, o: ml-i }\n  - { r: expuesto-por, o: mendez }\n---\nB\n"
    )
    (tmp_vault / "clase2.md").write_text(
        "---\ntriples:\n  - { r: tema-de, o: ml-i }\n---\nB\n"
    )

    backend = GraphBackend(vault_root=tmp_vault)
    backend.rebuild_index()

    related = backend.traverse(node="ml-i", relation="tema-de", depth=1, reverse=True)
    relative_paths = sorted(r.relative_path for r in related)
    assert "clase1.md" in relative_paths
    assert "clase2.md" in relative_paths


def test_no_triples_returns_empty(tmp_vault: Path):
    (tmp_vault / "n.md").write_text("plain note no frontmatter")
    backend = GraphBackend(vault_root=tmp_vault)
    backend.rebuild_index()
    assert backend.traverse(node="x", relation="r", depth=1, reverse=True) == []


def test_forward_traversal_raises(tmp_vault: Path):
    import pytest
    backend = GraphBackend(vault_root=tmp_vault)
    backend.rebuild_index()
    with pytest.raises(NotImplementedError):
        backend.traverse(node="x", relation="r", depth=1, reverse=False)
