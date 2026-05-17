import sqlite3
from dataclasses import dataclass
from pathlib import Path
import yaml

from rufino.engine.query.note_ref import NoteRef


@dataclass
class GraphBackend:
    vault_root: Path

    def __post_init__(self) -> None:
        self._db_path = self.vault_root / "_meta" / "triples.sqlite"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS triples ("
            "subject_path TEXT, relation TEXT, object TEXT, "
            "PRIMARY KEY(subject_path, relation, object))"
        )

    def rebuild_index(self) -> None:
        self._conn.execute("DELETE FROM triples")
        for p in self.vault_root.rglob("*.md"):
            text = p.read_text()
            if not text.startswith("---\n"):
                continue
            try:
                _, fm_block, _ = text.split("---\n", 2)
            except ValueError:
                continue
            fm = yaml.safe_load(fm_block) or {}
            triples = fm.get("triples", [])
            if not isinstance(triples, list):
                continue
            rel_path = str(p.relative_to(self.vault_root))
            for entry in triples:
                if isinstance(entry, dict) and "r" in entry and "o" in entry:
                    self._conn.execute(
                        "INSERT OR IGNORE INTO triples VALUES (?, ?, ?)",
                        (rel_path, entry["r"], entry["o"]),
                    )
        self._conn.commit()

    def traverse(
        self,
        *,
        node: str,
        relation: str,
        depth: int,
        reverse: bool = False,
    ) -> list[NoteRef]:
        """Find notes connected to `node` via `relation`.

        depth=1 only (multi-hop deferred to v1.1).
        reverse=True: find notes whose triple POINTS TO `node` (inbound).
        reverse=False: deferred — subject_path is a note path, not a node id.
        """
        if reverse:
            cur = self._conn.execute(
                "SELECT subject_path FROM triples WHERE relation = ? AND object = ?",
                (relation, node),
            )
            return [NoteRef(relative_path=row[0]) for row in cur.fetchall()]
        return []
