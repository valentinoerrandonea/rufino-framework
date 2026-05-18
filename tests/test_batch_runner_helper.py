import asyncio
import os
from pathlib import Path

import pytest

from rufino.engine.process.batch.runner_helper import (
    ClaudeResult,
    run_claude,
)


FAKE_DIR = (Path(__file__).parent / "fixtures" / "fake_claude").resolve()


@pytest.fixture(autouse=True)
def _fake_on_path(monkeypatch):
    monkeypatch.setenv("PATH", str(FAKE_DIR) + os.pathsep + os.environ["PATH"])


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
