from pathlib import Path

import pytest
import yaml

from rufino.runtime.embedder.ollama import OllamaEmbedder
from rufino.runtime.embedder.resolve import (
    NoopEmbedder,
    resolve_embedder,
    write_vault_state,
)


def _write(p: Path, data: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(data), encoding="utf-8")


def test_resolve_missing_state_returns_noop(tmp_path: Path) -> None:
    emb = resolve_embedder(vault_slug="facultad", state_dir=tmp_path)
    assert isinstance(emb, NoopEmbedder)


def test_resolve_enabled_false_returns_noop(tmp_path: Path) -> None:
    _write(
        tmp_path / "vaults" / "facultad.yaml",
        {"vault_slug": "facultad",
         "embeddings": {"enabled": False, "backend": "ollama", "model": "nomic-embed-text"}},
    )
    emb = resolve_embedder(vault_slug="facultad", state_dir=tmp_path)
    assert isinstance(emb, NoopEmbedder)


def test_resolve_enabled_true_returns_ollama(tmp_path: Path) -> None:
    _write(
        tmp_path / "vaults" / "facultad.yaml",
        {"vault_slug": "facultad",
         "embeddings": {"enabled": True, "backend": "ollama", "model": "nomic-embed-text"}},
    )
    emb = resolve_embedder(vault_slug="facultad", state_dir=tmp_path)
    assert isinstance(emb, OllamaEmbedder)
    assert emb.model == "nomic-embed-text"


def test_resolve_corrupt_yaml_raises(tmp_path: Path) -> None:
    p = tmp_path / "vaults" / "facultad.yaml"
    p.parent.mkdir(parents=True)
    p.write_text("not: valid: yaml: nope: [", encoding="utf-8")
    with pytest.raises(RuntimeError, match="corrupted"):
        resolve_embedder(vault_slug="facultad", state_dir=tmp_path)


def test_resolve_unknown_backend_raises(tmp_path: Path) -> None:
    _write(
        tmp_path / "vaults" / "facultad.yaml",
        {"embeddings": {"enabled": True, "backend": "openai"}},
    )
    with pytest.raises(RuntimeError, match="unknown embedder backend"):
        resolve_embedder(vault_slug="facultad", state_dir=tmp_path)


def test_resolve_enabled_without_backend_raises(tmp_path: Path) -> None:
    """A yaml with enabled=true but no backend should not silently default."""
    _write(
        tmp_path / "vaults" / "facultad.yaml",
        {"embeddings": {"enabled": True}},
    )
    with pytest.raises(RuntimeError, match="no backend"):
        resolve_embedder(vault_slug="facultad", state_dir=tmp_path)


def test_resolve_nonexistent_state_dir_returns_noop(tmp_path: Path) -> None:
    """An entirely missing state-dir (not just a missing yaml) returns Noop."""
    emb = resolve_embedder(
        vault_slug="any", state_dir=tmp_path / "does-not-exist",
    )
    assert isinstance(emb, NoopEmbedder)


def test_noop_embed_raises_with_helpful_message() -> None:
    emb = NoopEmbedder()
    with pytest.raises(NotImplementedError, match="enable-embeddings"):
        emb.embed("x")


def test_write_vault_state_creates_atomic(tmp_path: Path) -> None:
    write_vault_state(
        vault_slug="facultad", state_dir=tmp_path,
        embeddings_enabled=True,
    )
    p = tmp_path / "vaults" / "facultad.yaml"
    assert p.exists()
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert data["vault_slug"] == "facultad"
    assert data["embeddings"]["enabled"] is True
    assert data["embeddings"]["backend"] == "ollama"
    assert data["embeddings"]["model"] == "nomic-embed-text"


def test_write_vault_state_overwrites_existing(tmp_path: Path) -> None:
    write_vault_state(vault_slug="v", state_dir=tmp_path, embeddings_enabled=False)
    write_vault_state(vault_slug="v", state_dir=tmp_path, embeddings_enabled=True)
    data = yaml.safe_load((tmp_path / "vaults" / "v.yaml").read_text(encoding="utf-8"))
    assert data["embeddings"]["enabled"] is True


def test_write_vault_state_leaves_no_tempfile(tmp_path: Path) -> None:
    write_vault_state(vault_slug="x", state_dir=tmp_path, embeddings_enabled=True)
    leftovers = [
        p.name for p in (tmp_path / "vaults").iterdir() if p.name != "x.yaml"
    ]
    assert leftovers == []
