"""bootstrap_cmd whitelists exactly the CLI surface the wizard is allowed
to invoke through Claude's shell tool. v0.2 adds process-batch, detect/
enable-embeddings, and install-ingest."""
import subprocess

from click.testing import CliRunner

from rufino.cli import cli


def _captured_argv(monkeypatch):
    captured: list[list[str]] = []

    class _FakeProc:
        returncode = 0

    def fake_run(argv, **kwargs):
        captured.append(argv)
        return _FakeProc()

    monkeypatch.setattr(subprocess, "run", fake_run)
    return captured


def test_bootstrap_allowed_tools_includes_v0_2_commands(monkeypatch):
    captured = _captured_argv(monkeypatch)
    runner = CliRunner()
    result = runner.invoke(cli, ["bootstrap"])
    assert result.exit_code == 0, result.output
    assert captured, "subprocess.run never called"
    argv = captured[0]
    allowed_idx = argv.index("--allowedTools")
    allowed = argv[allowed_idx + 1]
    for tool in (
        "Bash(rufino materialize:*)",
        "Bash(rufino query:*)",
        "Bash(rufino process-batch:*)",
        "Bash(rufino detect-embeddings:*)",
        "Bash(rufino enable-embeddings:*)",
        "Bash(rufino install-ingest:*)",
    ):
        assert tool in allowed, f"missing whitelist entry: {tool}"
