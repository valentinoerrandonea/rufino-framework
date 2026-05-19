import os
from dataclasses import dataclass, field
from typing import Optional


# Pin commit SHA to keep hybrid search reproducible across hosts. Verified
# against https://huggingface.co/BAAI/bge-reranker-base/commits/main (2026-05-19).
_DEFAULT_MODEL = "BAAI/bge-reranker-base"
_DEFAULT_REVISION = "2cfc18c9415c912f9d8155881c133215df768a70"


@dataclass
class CrossEncoderReranker:
    """Lazy-loaded cross-encoder for hybrid-search rerank.

    The sentence-transformers import is deferred until first use so that
    CLI commands that never call rerank() don't pay the model-load cost.
    Model and revision can be overridden via ``RUFINO_RERANKER_MODEL`` and
    ``RUFINO_RERANKER_REVISION`` env vars for testing or local pinning.
    """
    model_name: str = _DEFAULT_MODEL
    _model: Optional[object] = field(default=None, init=False, repr=False)

    def _load_model(self) -> object:
        if self._model is None:
            from sentence_transformers import CrossEncoder
            model_name = os.environ.get("RUFINO_RERANKER_MODEL", self.model_name)
            revision = os.environ.get("RUFINO_RERANKER_REVISION", _DEFAULT_REVISION)
            self._model = CrossEncoder(model_name, revision=revision)
        return self._model

    def rerank(self, query: str, candidates: list[str]) -> list[str]:
        if not candidates:
            return []
        model = self._load_model()
        pairs = [(query, c) for c in candidates]
        scores = model.predict(pairs)
        ranked = sorted(zip(candidates, scores), key=lambda x: x[1], reverse=True)
        return [c for c, _ in ranked]
