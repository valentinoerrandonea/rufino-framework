from pathlib import Path
from rufino.engine.ingest.cursor import CursorStore


def test_cursor_initial_is_none(tmp_path: Path):
    store = CursorStore(tmp_path / "cursors.json")
    assert store.get("belo") is None


def test_cursor_set_and_get(tmp_path: Path):
    store = CursorStore(tmp_path / "cursors.json")
    store.set("belo", "2026-05-16T10:00:00Z")
    assert store.get("belo") == "2026-05-16T10:00:00Z"


def test_cursor_persists(tmp_path: Path):
    p = tmp_path / "cursors.json"
    s1 = CursorStore(p)
    s1.set("belo", "X")
    s2 = CursorStore(p)
    assert s2.get("belo") == "X"
