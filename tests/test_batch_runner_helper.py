import asyncio
import os

import pytest

from rufino.engine.process.batch import runner_helper
from rufino.engine.process.batch.runner_helper import (
    ClaudeResult,
    WorkerResult,
    run_claude,
)


@pytest.fixture(autouse=True)
def _fake_on_path(fake_claude_on_path):
    """Autouse delegate to shared conftest fixture (FAKE_CLAUDE_DIR on PATH)."""
    yield


def test_run_claude_writes_outputs(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "augment")
    note = tmp_path / "n.md"
    note.write_text("# n\n")
    monkeypatch.setenv("FAKE_CLAUDE_NOTES", str(note))

    result = asyncio.run(run_claude(
        argv=["claude", "-p", "--system-prompt", "x", "--", "go"],
        cwd=tmp_path,
        env=os.environ.copy(),
        timeout_seconds=30.0,
    ))
    assert isinstance(result, ClaudeResult)
    assert result.exit_code == 0
    assert (tmp_path / "augmented" / "n.md").exists()
    assert (tmp_path / "deltas" / "n.json").exists()


def test_run_claude_timeout(tmp_path, monkeypatch):
    """Simulate timeout: fake_claude in 'hang' mode never returns."""
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "hang")

    result = asyncio.run(run_claude(
        argv=["claude", "-p"],
        cwd=tmp_path,
        env=os.environ.copy(),
        timeout_seconds=0.5,
    ))
    assert result.exit_code == 124  # timeout sentinel


def test_run_claude_session_expired(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "session_expired")
    result = asyncio.run(run_claude(
        argv=["claude", "-p"],
        cwd=tmp_path,
        env=os.environ.copy(),
        timeout_seconds=30.0,
    ))
    assert result.exit_code == 41


def test_run_claude_strips_nested_session_markers(tmp_path, monkeypatch):
    """A nested Claude Code session sets CLAUDECODE; the worker `claude`
    aborts if it sees it. run_claude must strip the marker before spawning."""
    captured: dict[str, dict[str, str]] = {}

    async def _spy(*, cmd, cwd, timeout, env):
        captured["env"] = env
        return WorkerResult(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(runner_helper, "run_claude_worker", _spy)

    asyncio.run(run_claude(
        argv=["claude", "-p"],
        cwd=tmp_path,
        env={"CLAUDECODE": "1", "CLAUDE_CODE_ENTRYPOINT": "cli", "PATH": "/x"},
        timeout_seconds=30.0,
    ))

    assert "CLAUDECODE" not in captured["env"]
    assert "CLAUDE_CODE_ENTRYPOINT" not in captured["env"]
    assert captured["env"]["PATH"] == "/x"
