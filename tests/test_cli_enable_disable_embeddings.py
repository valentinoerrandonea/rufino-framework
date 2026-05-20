from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml
from click.testing import CliRunner

from rufino.cli import cli


def _ok_detect():
    from rufino.runtime.embedder.detect import OllamaDetection
    return OllamaDetection(True, True, True, None)


def _fail_detect():
    from rufino.runtime.embedder.detect import OllamaDetection
    return OllamaDetection(True, True, False, "model not pulled")


def test_enable_embeddings_writes_yaml_and_rebuilds(tmp_path: Path) -> None:
    vault = tmp_path / "v"
    vault.mkdir()
    state = tmp_path / "state"

    fake_ql = MagicMock()
    with patch("rufino.runtime.embedder.detect.detect_ollama", return_value=_ok_detect()), \
         patch("rufino.cli.QueryLayer", return_value=fake_ql):
        result = CliRunner().invoke(
            cli,
            ["enable-embeddings", "--vault", str(vault), "--state-dir", str(state)],
        )
    assert result.exit_code == 0, result.output

    from rufino.runtime.vault_slug import compute_vault_slug
    slug = compute_vault_slug(vault)
    yaml_path = state / "vaults" / f"{slug}.yaml"
    assert yaml_path.exists()
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    assert data["embeddings"]["enabled"] is True
    fake_ql.rebuild_indices.assert_called_once()


def test_enable_embeddings_fails_when_ollama_missing(tmp_path: Path) -> None:
    vault = tmp_path / "v"
    vault.mkdir()
    state = tmp_path / "state"

    with patch("rufino.runtime.embedder.detect.detect_ollama", return_value=_fail_detect()):
        result = CliRunner().invoke(
            cli,
            ["enable-embeddings", "--vault", str(vault), "--state-dir", str(state)],
        )
    assert result.exit_code == 1
    # detect fires before any mkdir, so state/vaults must not exist at all.
    assert not (state / "vaults").exists()


def test_enable_embeddings_does_not_write_state_when_rebuild_fails(
    tmp_path: Path,
) -> None:
    """If rebuild_indices raises, the per-vault state must NOT be flipped to
    enabled=true (otherwise subsequent queries point at a half-built index)."""
    vault = tmp_path / "v"
    vault.mkdir()
    state = tmp_path / "state"

    fake_ql = MagicMock()
    fake_ql.rebuild_indices.side_effect = RuntimeError("ollama dropped mid-rebuild")
    with patch("rufino.runtime.embedder.detect.detect_ollama", return_value=_ok_detect()), \
         patch("rufino.cli.QueryLayer", return_value=fake_ql):
        result = CliRunner().invoke(
            cli,
            ["enable-embeddings", "--vault", str(vault), "--state-dir", str(state)],
        )
    assert result.exit_code != 0
    # No vault state should be written.
    assert not (state / "vaults").exists()


def test_disable_embeddings_writes_yaml_disabled(tmp_path: Path) -> None:
    vault = tmp_path / "v"
    vault.mkdir()
    state = tmp_path / "state"

    result = CliRunner().invoke(
        cli, ["disable-embeddings", "--vault", str(vault), "--state-dir", str(state)],
    )
    assert result.exit_code == 0, result.output

    from rufino.runtime.vault_slug import compute_vault_slug
    slug = compute_vault_slug(vault)
    data = yaml.safe_load((state / "vaults" / f"{slug}.yaml").read_text(encoding="utf-8"))
    assert data["embeddings"]["enabled"] is False


def test_disable_embeddings_idempotent(tmp_path: Path) -> None:
    vault = tmp_path / "v"
    vault.mkdir()
    state = tmp_path / "state"

    r1 = CliRunner().invoke(cli, ["disable-embeddings", "--vault", str(vault), "--state-dir", str(state)])
    r2 = CliRunner().invoke(cli, ["disable-embeddings", "--vault", str(vault), "--state-dir", str(state)])
    assert r1.exit_code == 0
    assert r2.exit_code == 0


def test_enable_embeddings_works_without_state_dir_flag(tmp_path: Path, monkeypatch) -> None:
    """Regression: Codex P1 #3 — el wizard usa `enable-embeddings --vault X` sin --state-dir.

    Comportamiento esperado: el comando aplica ~/.rufino/state como default,
    igual que query / mcp-server / output. Sin esto, el flow guiado del
    wizard falla con un Click error."""
    vault = tmp_path / "v"
    vault.mkdir()
    fake_state = tmp_path / ".rufino" / "state"
    monkeypatch.setattr("rufino.cli.DEFAULT_STATE_DIR", fake_state)

    fake_ql = MagicMock()
    with patch("rufino.runtime.embedder.detect.detect_ollama", return_value=_ok_detect()), \
         patch("rufino.cli.QueryLayer", return_value=fake_ql):
        result = CliRunner().invoke(cli, ["enable-embeddings", "--vault", str(vault)])
    assert result.exit_code == 0, result.output

    from rufino.runtime.vault_slug import compute_vault_slug
    slug = compute_vault_slug(vault)
    yaml_path = fake_state / "vaults" / f"{slug}.yaml"
    assert yaml_path.exists()


def test_disable_embeddings_works_without_state_dir_flag(tmp_path: Path, monkeypatch) -> None:
    vault = tmp_path / "v"
    vault.mkdir()
    fake_state = tmp_path / ".rufino" / "state"
    monkeypatch.setattr("rufino.cli.DEFAULT_STATE_DIR", fake_state)

    result = CliRunner().invoke(cli, ["disable-embeddings", "--vault", str(vault)])
    assert result.exit_code == 0, result.output

    from rufino.runtime.vault_slug import compute_vault_slug
    slug = compute_vault_slug(vault)
    yaml_path = fake_state / "vaults" / f"{slug}.yaml"
    assert yaml_path.exists()


def test_enable_embeddings_rolls_back_partial_sqlite_on_failure(tmp_path: Path) -> None:
    """F11 — si rebuild_indices escribe sqlite parcial y luego raise, el rollback
    debe limpiar el _meta/embeddings.sqlite para que un re-enable no duplique.
    """
    vault = tmp_path / "v"
    vault.mkdir()
    state = tmp_path / "state"
    meta = vault / "_meta"
    meta.mkdir()

    def fake_rebuild(self):
        # Simula que rebuild escribió un sqlite parcial antes de fallar.
        (meta / "embeddings.sqlite").write_bytes(b"PARTIAL")
        (meta / "graph.sqlite").write_bytes(b"PARTIAL")
        raise RuntimeError("ollama dropped mid-rebuild")

    with patch(
        "rufino.runtime.embedder.detect.detect_ollama",
        return_value=_ok_detect(),
    ), patch(
        "rufino.cli.QueryLayer.rebuild_indices",
        fake_rebuild,
    ):
        result = CliRunner().invoke(
            cli,
            ["enable-embeddings", "--vault", str(vault), "--state-dir", str(state)],
        )
    assert result.exit_code != 0
    # State no escrito.
    assert not (state / "vaults").exists()
    # Sqlite parcial limpiado.
    assert not (meta / "embeddings.sqlite").exists()
    assert not (meta / "graph.sqlite").exists()


def test_enable_embeddings_refuses_stale_snapshot(tmp_path: Path) -> None:
    """CR2-2 — Si hay un .rufino-bak de una corrida anterior crasheada, abort
    en lugar de sobreescribirlo con la live index posiblemente corrupta.
    """
    vault = tmp_path / "v"
    vault.mkdir()
    meta = vault / "_meta"
    meta.mkdir()
    # Simula la live index (parcial) + un snapshot leftover de una corrida previa.
    (meta / "embeddings.sqlite").write_bytes(b"PARTIAL LIVE")
    (meta / "embeddings.sqlite.rufino-bak").write_bytes(b"GOOD PRIOR")

    with patch(
        "rufino.runtime.embedder.detect.detect_ollama",
        return_value=_ok_detect(),
    ):
        result = CliRunner().invoke(
            cli, ["enable-embeddings", "--vault", str(vault),
                  "--state-dir", str(tmp_path / "state")],
        )
    assert result.exit_code != 0
    assert "stale snapshot" in result.output.lower()
    # El bak no debe haberse tocado.
    assert (meta / "embeddings.sqlite.rufino-bak").read_bytes() == b"GOOD PRIOR"


def test_enable_embeddings_rolls_back_when_state_write_fails(tmp_path: Path) -> None:
    """F11 — si write_vault_state crashea después de rebuild, el sqlite y graph
    nuevos deben revertirse al snapshot previo (o limpiarse si no había)."""
    vault = tmp_path / "v"
    vault.mkdir()
    state = tmp_path / "state"
    meta = vault / "_meta"
    meta.mkdir()

    def fake_rebuild(self):
        (meta / "embeddings.sqlite").write_bytes(b"NEW")
        (meta / "graph.sqlite").write_bytes(b"NEW")

    def boom_write(**kwargs):
        raise OSError("disk full")

    with patch(
        "rufino.runtime.embedder.detect.detect_ollama",
        return_value=_ok_detect(),
    ), patch(
        "rufino.cli.QueryLayer.rebuild_indices",
        fake_rebuild,
    ), patch("rufino.cli.write_vault_state", boom_write):
        result = CliRunner().invoke(
            cli,
            ["enable-embeddings", "--vault", str(vault), "--state-dir", str(state)],
        )
    assert result.exit_code != 0
    # No quedaron sqlites nuevos (no había snapshot previo, así que se borran).
    assert not (meta / "embeddings.sqlite").exists()
    assert not (meta / "graph.sqlite").exists()
