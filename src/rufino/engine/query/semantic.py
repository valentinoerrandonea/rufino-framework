import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from rufino.engine.query.filters import iter_user_notes
from rufino.engine.query.note_ref import NoteRef


class EmbeddingProvider(Protocol):
    def embed(self, text: str) -> list[float]: ...


@dataclass
class SemanticBackend:
    """Semantic search via embeddings.

    Vectors are persisted as ``json.dumps(list[float])`` in TEXT columns;
    cosine similarity is computed in pure Python at query time (sqlite-vec
    integration is on the roadmap as a perf optimization).

    The sqlite file is created lazily on the first ``rebuild_index`` or
    ``search`` call. With a ``NoopEmbedder`` (embeddings disabled for this
    vault) the connection is never opened, so a vault that never enables
    semantic search has no phantom ``_meta/embeddings.sqlite`` polluting it.
    """
    vault_root: Path
    embedder: EmbeddingProvider

    def __post_init__(self) -> None:
        self._db_path = self.vault_root / "_meta" / "embeddings.sqlite"
        self._conn: sqlite3.Connection | None = None

    def _conn_lazy(self) -> sqlite3.Connection:
        if self._conn is None:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self._db_path)
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS notes "
                "(rel_path TEXT PRIMARY KEY, vector TEXT)"
            )
        return self._conn

    def rebuild_index(self) -> None:
        conn = self._conn_lazy()
        with conn:
            conn.execute("DELETE FROM notes")
            for p in iter_user_notes(self.vault_root):
                text = p.read_text(encoding="utf-8", errors="replace")
                vec = self.embedder.embed(text)
                rel = str(p.relative_to(self.vault_root))
                conn.execute(
                    "INSERT OR REPLACE INTO notes VALUES (?, ?)",
                    (rel, json.dumps(vec)),
                )

    def search(self, query: str, *, k: int) -> list[NoteRef]:
        q_vec = self.embedder.embed(query)
        conn = self._conn_lazy()
        cur = conn.execute("SELECT rel_path, vector FROM notes")
        scored: list[tuple[str, float]] = []
        for rel, vec_json in cur.fetchall():
            vec = json.loads(vec_json)
            scored.append((rel, _cosine(q_vec, vec)))
        scored.sort(key=lambda x: x[1], reverse=True)
        return [NoteRef(relative_path=p, score=s) for p, s in scored[:k]]


def _cosine(a: list[float], b: list[float]) -> float:
    import math
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1e-9
    nb = math.sqrt(sum(y * y for y in b)) or 1e-9
    return dot / (na * nb)
