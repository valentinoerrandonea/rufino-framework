import sqlite3
from pathlib import Path


class DedupStore:
    """SQLite-backed dedup tracking per source."""

    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS seen (source TEXT, fact_id TEXT, PRIMARY KEY(source, fact_id))"
        )
        self._conn.commit()

    def is_new(self, *, source: str, fact_id: str) -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM seen WHERE source = ? AND fact_id = ?",
            (source, fact_id),
        )
        return cur.fetchone() is None

    def mark_seen(self, *, source: str, fact_id: str) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO seen (source, fact_id) VALUES (?, ?)",
            (source, fact_id),
        )
        self._conn.commit()
