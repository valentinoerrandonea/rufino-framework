from pathlib import Path
from rufino.engine.query.lexical import LexicalBackend
from rufino.engine.query.note_ref import NoteRef


def test_lexical_finds_word_across_notes(tmp_vault: Path):
    (tmp_vault / "a.md").write_text("regresión logística estudio")
    (tmp_vault / "b.md").write_text("svm y trees")
    (tmp_vault / "c.md").write_text("notes about regresión lineal")

    backend = LexicalBackend(vault_root=tmp_vault)
    results = backend.search("regresión")
    paths = sorted(r.relative_path for r in results)
    assert "a.md" in paths
    assert "c.md" in paths
    assert "b.md" not in paths


def test_lexical_returns_empty_when_no_match(tmp_vault: Path):
    (tmp_vault / "a.md").write_text("hello")
    backend = LexicalBackend(vault_root=tmp_vault)
    assert backend.search("nonexistent_xyz") == []


def test_lexical_excludes_meta_and_dot_dirs(tmp_vault: Path):
    """Search must not return notes inside _meta/, .obsidian/, .git/ etc."""
    (tmp_vault / "real.md").write_text("regresion logistica")
    (tmp_vault / ".obsidian").mkdir()
    (tmp_vault / ".obsidian" / "template.md").write_text("regresion logistica")
    (tmp_vault / "_meta").mkdir()
    (tmp_vault / "_meta" / "indexed.md").write_text("regresion logistica")
    (tmp_vault / ".git").mkdir()
    (tmp_vault / ".git" / "msg.md").write_text("regresion logistica")

    backend = LexicalBackend(vault_root=tmp_vault)
    paths = sorted(r.relative_path for r in backend.search("regresion"))
    assert paths == ["real.md"]


def test_lexical_python_fallback_excludes_meta_and_dot_dirs(tmp_vault: Path, monkeypatch):
    """When ripgrep is missing, the Python fallback must also respect exclusions."""
    (tmp_vault / "real.md").write_text("foo")
    (tmp_vault / "_meta").mkdir()
    (tmp_vault / "_meta" / "system.md").write_text("foo")

    backend = LexicalBackend(vault_root=tmp_vault)
    results = backend._python_fallback("foo")
    paths = sorted(r.relative_path for r in results)
    assert paths == ["real.md"]


def test_lexical_handles_dash_prefix_query(tmp_vault: Path):
    """Queries starting with `-` must not be interpreted as ripgrep flags."""
    (tmp_vault / "a.md").write_text("--help is the flag we search for")
    backend = LexicalBackend(vault_root=tmp_vault)
    results = backend.search("--help")
    paths = [r.relative_path for r in results]
    assert "a.md" in paths


import pytest


@pytest.mark.parametrize("query", ["c++", "a.b", "f(x)", "[draft]"])
def test_lexical_handles_regex_metachars_as_literal(tmp_path: Path, query: str):
    """Queries with regex special chars must match the literal text."""
    from rufino.engine.query.lexical import LexicalBackend
    vault = tmp_path / "v"
    vault.mkdir()
    (vault / "note.md").write_text(f"contains {query} literally", encoding="utf-8")
    results = LexicalBackend(vault_root=vault).search(query)
    assert any(r.relative_path.endswith("note.md") for r in results), (
        f"query {query!r} did not match its literal occurrence"
    )
