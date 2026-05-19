from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CrossEncoderReranker:
    """Lazy-loaded cross-encoder for hybrid-search rerank.

    The sentence-transformers import is deferred until first use so that
    CLI commands that never call rerank() don't pay the model-load cost.
    """
    model_name: str = "BAAI/bge-reranker-base"
    _model: Optional[object] = field(default=None, init=False, repr=False)

    def _load_model(self) -> object:
        if self._model is None:
            from sentence_transformers import CrossEncoder
            self._model = CrossEncoder(self.model_name)
        return self._model

    def rerank(self, query: str, candidates: list[str]) -> list[str]:
        if not candidates:
            return []
        model = self._load_model()
        pairs = [(query, c) for c in candidates]
        scores = model.predict(pairs)
        ranked = sorted(zip(candidates, scores), key=lambda x: x[1], reverse=True)
        return [c for c, _ in ranked]
