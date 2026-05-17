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
