from dataclasses import dataclass
from pathlib import Path

from rufino.engine.query.note_ref import NoteRef
from rufino.engine.query.lexical import LexicalBackend
from rufino.engine.query.semantic import SemanticBackend, EmbeddingProvider
from rufino.engine.query.graph import GraphBackend


VALID_MODES = {"lexical", "semantic", "hybrid"}


@dataclass
class QueryLayer:
    vault_root: Path
    embedder: EmbeddingProvider

    def __post_init__(self) -> None:
        self._lex = LexicalBackend(vault_root=self.vault_root)
        self._sem = SemanticBackend(vault_root=self.vault_root, embedder=self.embedder)
        self._graph = GraphBackend(vault_root=self.vault_root)

    def rebuild_indices(self) -> None:
        self._sem.rebuild_index()
        self._graph.rebuild_index()

    def search(self, query: str, *, mode: str = "hybrid", k: int = 10) -> list[NoteRef]:
        if mode not in VALID_MODES:
            raise ValueError(f"mode must be in {VALID_MODES}, got {mode!r}")
        if mode == "lexical":
            return self._lex.search(query)
        if mode == "semantic":
            return self._sem.search(query, k=k)
        lex = self._lex.search(query)
        sem = self._sem.search(query, k=k)
        seen: dict[str, NoteRef] = {}
        for r in sem + lex:
            existing = seen.get(r.relative_path)
            if existing is None or r.score > existing.score:
                seen[r.relative_path] = r
        return sorted(seen.values(), key=lambda r: r.score, reverse=True)[:k]

    def traverse(
        self, *, node: str, relation: str, depth: int, reverse: bool = False,
    ) -> list[NoteRef]:
        return self._graph.traverse(node=node, relation=relation, depth=depth, reverse=reverse)
