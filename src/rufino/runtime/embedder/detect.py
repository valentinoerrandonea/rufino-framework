import shutil
from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class OllamaDetection:
    binary_present: bool
    server_running: bool
    model_installed: bool
    error: str | None


def detect_ollama(
    *,
    base_url: str = "http://localhost:11434",
    model: str = "nomic-embed-text",
) -> OllamaDetection:
    """Probe the local Ollama install for an embedding-ready setup.

    Returns a structured detection result so callers can decide how to
    react (e.g. fail enable-embeddings vs. just warn). Network errors are
    treated as "server not running" rather than propagated.
    """
    if shutil.which("ollama") is None:
        return OllamaDetection(False, False, False, "ollama binary not in PATH")
    try:
        resp = httpx.get(f"{base_url}/api/tags", timeout=3.0)
        resp.raise_for_status()
    except Exception as e:
        return OllamaDetection(True, False, False, f"ollama server not responding: {e}")
    models = [m.get("name", "") for m in resp.json().get("models", [])]
    found = any(m.startswith(model) for m in models)
    return OllamaDetection(
        binary_present=True,
        server_running=True,
        model_installed=found,
        error=None if found else f"model {model!r} not pulled",
    )
