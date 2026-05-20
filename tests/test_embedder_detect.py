from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from rufino.cli import cli
from rufino.runtime.embedder.detect import detect_ollama


def test_detect_all_present() -> None:
    with patch("rufino.runtime.embedder.detect.shutil.which",
               return_value="/usr/local/bin/ollama"), \
         patch("rufino.runtime.embedder.detect.httpx.get") as mget:
        mget.return_value = MagicMock(
            status_code=200,
            json=lambda: {"models": [{"name": "nomic-embed-text:latest"}]},
        )
        mget.return_value.raise_for_status = MagicMock()
        r = detect_ollama()
    assert r.binary_present and r.server_running and r.model_installed
    assert r.error is None


def test_detect_no_binary() -> None:
    with patch("rufino.runtime.embedder.detect.shutil.which", return_value=None):
        r = detect_ollama()
    assert not r.binary_present
    assert not r.server_running
    assert not r.model_installed
    assert r.error is not None


def test_detect_server_down() -> None:
    import httpx
    with patch("rufino.runtime.embedder.detect.shutil.which",
               return_value="/usr/local/bin/ollama"), \
         patch("rufino.runtime.embedder.detect.httpx.get",
               side_effect=httpx.ConnectError("nope")):
        r = detect_ollama()
    assert r.binary_present
    assert not r.server_running
    assert "not responding" in (r.error or "")


def test_detect_model_missing() -> None:
    with patch("rufino.runtime.embedder.detect.shutil.which",
               return_value="/usr/local/bin/ollama"), \
         patch("rufino.runtime.embedder.detect.httpx.get") as mget:
        mget.return_value = MagicMock(
            status_code=200,
            json=lambda: {"models": [{"name": "llama3:latest"}]},
        )
        mget.return_value.raise_for_status = MagicMock()
        r = detect_ollama()
    assert r.binary_present and r.server_running
    assert not r.model_installed
    assert "nomic-embed-text" in (r.error or "")


def test_cli_detect_embeddings_ok() -> None:
    with patch("rufino.runtime.embedder.detect.shutil.which",
               return_value="/usr/local/bin/ollama"), \
         patch("rufino.runtime.embedder.detect.httpx.get") as mget:
        mget.return_value = MagicMock(
            status_code=200,
            json=lambda: {"models": [{"name": "nomic-embed-text:latest"}]},
        )
        mget.return_value.raise_for_status = MagicMock()
        result = CliRunner().invoke(cli, ["detect-embeddings"])
    assert result.exit_code == 0, result.output
    assert "OK" in result.output


def test_cli_detect_embeddings_not_ready() -> None:
    with patch("rufino.runtime.embedder.detect.shutil.which", return_value=None):
        result = CliRunner().invoke(cli, ["detect-embeddings"])
    assert result.exit_code == 1
    assert "NOT READY" in result.output
