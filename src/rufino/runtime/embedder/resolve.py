import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

import yaml

from rufino.runtime.embedder.ollama import OllamaEmbedder


@dataclass(frozen=True)
class NoopEmbedder:
    """Placeholder used when embeddings are disabled or unconfigured.

    Lexical search continues to work; semantic and hybrid modes raise on
    `.embed()` to surface the missing configuration loudly.
    """

    def embed(self, text: str) -> list[float]:
        raise NotImplementedError(
            "embeddings no configurados para este vault; "
            "corré `rufino enable-embeddings --vault X`"
        )


def _state_path(vault_slug: str, state_dir: Path) -> Path:
    return state_dir / "vaults" / f"{vault_slug}.yaml"


def resolve_embedder(*, vault_slug: str, state_dir: Path):
    """Return the embedder configured for `vault_slug` (or `NoopEmbedder`)."""
    p = _state_path(vault_slug, state_dir)
    if not p.exists():
        return NoopEmbedder()
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise RuntimeError(f"vault state corrupted at {p}: {e}") from e
    emb = data.get("embeddings", {}) or {}
    if not emb.get("enabled"):
        return NoopEmbedder()
    backend = emb.get("backend")
    if not backend:
        raise RuntimeError(
            f"vault state at {p} has embeddings.enabled=true but no backend; "
            f"corré `rufino enable-embeddings --vault X` para regenerarlo"
        )
    if backend == "ollama":
        return OllamaEmbedder(model=emb.get("model", "nomic-embed-text"))
    raise RuntimeError(f"unknown embedder backend {backend!r}")


def write_vault_state(
    *,
    vault_slug: str,
    state_dir: Path,
    embeddings_enabled: bool,
    backend: str = "ollama",
    model: str = "nomic-embed-text",
) -> None:
    """Atomically write per-vault embedding state to <state_dir>/vaults/<slug>.yaml."""
    target = _state_path(vault_slug, state_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "vault_slug": vault_slug,
        "embeddings": {
            "enabled": embeddings_enabled,
            "backend": backend,
            "model": model,
        },
    }
    fd, tmp = tempfile.mkstemp(dir=target.parent, suffix=".yaml")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.safe_dump(payload, f, sort_keys=False, allow_unicode=True)
        os.replace(tmp, target)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
