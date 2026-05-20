import logging
from dataclasses import dataclass
from pathlib import Path

from rufino.engine.query.note_ref import NoteRef
from rufino.engine.query.lexical import LexicalBackend
from rufino.engine.query.semantic import SemanticBackend, EmbeddingProvider
from rufino.engine.query.graph import GraphBackend
from rufino.runtime.embedder.cross_encoder import CrossEncoderReranker
from rufino.runtime.embedder.resolve import NoopEmbedder


VALID_MODES = {"lexical", "semantic", "hybrid"}

logger = logging.getLogger(__name__)


@dataclass
class QueryLayer:
    vault_root: Path
    embedder: EmbeddingProvider

    def __post_init__(self) -> None:
        self._lex = LexicalBackend(vault_root=self.vault_root)
        self._sem = SemanticBackend(vault_root=self.vault_root, embedder=self.embedder)
        self._graph = GraphBackend(vault_root=self.vault_root)
        self._reranker: CrossEncoderReranker | None = None

    def _get_reranker(self) -> CrossEncoderReranker:
        if self._reranker is None:
            self._reranker = CrossEncoderReranker()
        return self._reranker

    def embeddings_enabled(self) -> bool:
        """True si el embedder configurado puede producir vectores reales."""
        return not isinstance(self.embedder, NoopEmbedder)

    def rebuild_indices(self) -> None:
        # Lexical (ripgrep) is index-free, nothing to rebuild.
        self._sem.rebuild_index()
        self._graph.rebuild_index()

    def search(self, query: str, *, mode: str = "hybrid", k: int = 10) -> list[NoteRef]:
        if mode not in VALID_MODES:
            raise ValueError(f"mode must be in {VALID_MODES}, got {mode!r}")
        if mode == "lexical":
            return self._lex.search(query)
        if mode == "semantic":
            return self._sem.search(query, k=k)
        # mode == "hybrid": union lex + sem then rerank with a cross-encoder.
        # If the vault has no real embedder (NoopEmbedder), surface that loudly
        # rather than silently returning lexical-only results.
        if isinstance(self.embedder, NoopEmbedder):
            raise NotImplementedError(
                "embeddings no configurados para este vault; "
                "corré `rufino enable-embeddings --vault X` antes de usar --mode=hybrid"
            )
        lex = self._lex.search(query)
        sem = self._sem.search(query, k=k)
        seen: set[str] = set()
        union: list[NoteRef] = []
        for n in lex + sem:
            if n.relative_path not in seen:
                seen.add(n.relative_path)
                union.append(n)
        if not union:
            return []
        rer = self._get_reranker()
        contents: list[str] = []
        for n in union:
            try:
                contents.append(
                    (self.vault_root / n.relative_path).read_text(
                        encoding="utf-8", errors="replace",
                    )
                )
            except OSError:
                contents.append("")
        try:
            order = rer.rerank(query, contents)
        except (ImportError, OSError, RuntimeError) as e:
            # Cualquier fallo del reranker (lib no instalada, hub network
            # down, CUDA OOM, etc.) degrada a la unión sin rerank. El log
            # loudly avisa al usuario para que vea qué falla.
            logger.warning(
                "hybrid search reranker unavailable (%s); "
                "returning union without rerank",
                e,
            )
            return union[:k]
        # Map reranked content back to NoteRefs. Multiple notes could have the
        # same content, so consume each NoteRef once in order.
        by_content: dict[str, list[NoteRef]] = {}
        for c, n in zip(contents, union):
            by_content.setdefault(c, []).append(n)
        ordered: list[NoteRef] = []
        for c in order:
            if by_content.get(c):
                ordered.append(by_content[c].pop(0))
        return ordered[:k]

    def traverse(
        self, *, node: str, relation: str, depth: int, reverse: bool = False,
    ) -> list[NoteRef]:
        return self._graph.traverse(node=node, relation=relation, depth=depth, reverse=reverse)

    def run(self, query_string: str) -> list[str]:
        """Adapter for the QueryLayer Protocol used by context_injectors (Plan 3)."""
        return [r.relative_path for r in self.search(query_string, mode="hybrid")]
