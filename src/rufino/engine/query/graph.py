import sqlite3
from dataclasses import dataclass
from pathlib import Path
import yaml

from rufino.engine.query.filters import iter_user_notes
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
        with self._conn:
            self._conn.execute("DELETE FROM triples")
            for p in iter_user_notes(self.vault_root):
                text = p.read_text(encoding="utf-8", errors="replace")
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
                    if (
                        isinstance(entry, dict)
                        and isinstance(entry.get("r"), str)
                        and entry.get("o") is not None
                    ):
                        self._conn.execute(
                            "INSERT OR IGNORE INTO triples VALUES (?, ?, ?)",
                            (rel_path, entry["r"], str(entry["o"])),
                        )

    def traverse(
        self,
        *,
        node: str,
        relation: str,
        depth: int,
        reverse: bool = False,
    ) -> list[NoteRef]:
        """Find triple endpoints connected to `node` via `relation`.

        depth=1 only (multi-hop deferred to v1.1).
        reverse=True: `node` is an object; returns subject note paths pointing
        to it via `relation` (inbound).
        reverse=False (forward): `node` is a subject note path; returns the
        objects it relates to via `relation`. The object string is carried in
        NoteRef.relative_path for API uniformity; callers that need typing
        beyond a string should treat the field as opaque.
        """
        if depth != 1:
            raise NotImplementedError(
                "multi-hop traversal (depth > 1) deferred to v1.1"
            )
        if reverse:
            cur = self._conn.execute(
                "SELECT subject_path FROM triples WHERE relation = ? AND object = ?",
                (relation, node),
            )
        else:
            cur = self._conn.execute(
                "SELECT object FROM triples WHERE subject_path = ? AND relation = ?",
                (node, relation),
            )
        return [NoteRef(relative_path=row[0]) for row in cur.fetchall()]
