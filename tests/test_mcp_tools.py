from pathlib import Path
import pytest

from rufino.mcp_server.tools import (
    search_vault, find_note, list_triples_for_node,
    read_note, vault_stats, list_recent_notes,
)
from rufino.engine.query.api import QueryLayer


class FakeEmbeddings:
    def embed(self, text):
        import hashlib
        h = hashlib.sha256(text.encode()).digest()[:8]
        return [b / 255.0 for b in h]


def _make_ql(vault: Path) -> QueryLayer:
    ql = QueryLayer(vault_root=vault, embedder=FakeEmbeddings())
    ql.rebuild_indices()
    return ql


def test_search_vault_returns_paths(tmp_vault: Path):
    (tmp_vault / "x.md").write_text("regresion logistica")
    ql = _make_ql(tmp_vault)
    result = search_vault(ql, query="regresion", mode="lexical")
    assert "x.md" in result


def test_read_note_returns_content(tmp_vault: Path):
    (tmp_vault / "a.md").write_text("content here")
    ql = _make_ql(tmp_vault)
    assert read_note(ql, relative_path="a.md") == "content here"


def test_read_note_rejects_path_traversal(tmp_vault: Path):
    ql = _make_ql(tmp_vault)
    with pytest.raises(ValueError, match="outside"):
        read_note(ql, relative_path="../etc/passwd")


def test_read_note_rejects_symlink(tmp_vault: Path, tmp_path: Path):
    """A symlink inside the vault pointing outside must not be readable."""
    outside = tmp_path / "secret.txt"
    outside.write_text("top secret")
    link = tmp_vault / "innocent.md"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("filesystem does not support symlinks")

    ql = _make_ql(tmp_vault)
    with pytest.raises(ValueError, match="symlink"):
        read_note(ql, relative_path="innocent.md")


def test_vault_stats_reports_count(tmp_vault: Path):
    (tmp_vault / "a.md").write_text("x")
    (tmp_vault / "b.md").write_text("y")
    ql = _make_ql(tmp_vault)
    stats = vault_stats(ql)
    assert stats["note_count"] == 2


def test_list_recent_notes(tmp_vault: Path):
    import time
    (tmp_vault / "a.md").write_text("old")
    time.sleep(0.01)
    (tmp_vault / "b.md").write_text("new")
    ql = _make_ql(tmp_vault)
    recent = list_recent_notes(ql, k=2)
    assert recent[0] == "b.md"


def test_list_triples_for_node(tmp_vault: Path):
    (tmp_vault / "c.md").write_text(
        "---\ntriples:\n  - { r: tema-de, o: ml-i }\n---\nbody\n"
    )
    ql = _make_ql(tmp_vault)
    results = list_triples_for_node(ql, node="ml-i", relation="tema-de", reverse=True)
    assert "c.md" in results


def test_vault_stats_excludes_meta_and_dot_dirs(tmp_vault: Path):
    """Notes inside _meta/, .obsidian/, .git/ must not be counted."""
    (tmp_vault / "real.md").write_text("user note")
    (tmp_vault / ".obsidian").mkdir()
    (tmp_vault / ".obsidian" / "template.md").write_text("template")
    (tmp_vault / "_meta").mkdir(exist_ok=True)
    (tmp_vault / "_meta" / "indexed.md").write_text("system")
    ql = _make_ql(tmp_vault)
    assert vault_stats(ql)["note_count"] == 1


def test_list_recent_notes_excludes_meta_and_dot_dirs(tmp_vault: Path):
    (tmp_vault / "real.md").write_text("user")
    (tmp_vault / ".obsidian").mkdir()
    (tmp_vault / ".obsidian" / "x.md").write_text("template")
    ql = _make_ql(tmp_vault)
    assert list_recent_notes(ql, k=5) == ["real.md"]


def test_read_note_raises_on_non_utf8(tmp_vault: Path):
    """Binary or invalid UTF-8 must surface as ValueError, not silent garbage."""
    (tmp_vault / "bin.md").write_bytes(b"\xff\xfe\x00invalid utf-8")
    ql = _make_ql(tmp_vault)
    with pytest.raises(ValueError, match="UTF-8"):
        read_note(ql, relative_path="bin.md")
