from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class OllamaEmbedder:
    """Embedder backed by a local Ollama server.

    Synchronous, single-text API. Errors from httpx (timeouts, HTTP errors,
    connection failures) propagate to the caller; we intentionally do not
    swallow them so semantic-mode callers can surface accurate failure modes
    instead of silently returning empty vectors.
    """
    model: str = "nomic-embed-text"
    base_url: str = "http://localhost:11434"
    timeout: float = 30.0

    def embed(self, text: str) -> list[float]:
        resp = httpx.post(
            f"{self.base_url}/api/embeddings",
            json={"model": self.model, "prompt": text},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()["embedding"]
