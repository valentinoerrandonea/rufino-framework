"""CLI smoke test for `rufino process-batch`.

Uses --dry-run so no real claude subprocess is launched; we only verify
the wiring (option parsing, runner invocation, exit code, and output
includes the plan path).
"""
from click.testing import CliRunner

from rufino.cli import cli


def test_process_batch_dry_run(
    tmp_path, monkeypatch, batch_adapter, fake_claude_on_path
):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "augment")
    adapter = batch_adapter()
    source = tmp_path / "corpus"
    (source / "math").mkdir(parents=True)
    (source / "math" / "n1.md").write_text("# n\n")
    vault = tmp_path / "vault"

    runner = CliRunner()
    result = runner.invoke(cli, [
        "process-batch", str(source),
        "--adapter", str(adapter),
        "--vault", str(vault),
        "--dry-run",
    ])
    assert result.exit_code == 0, result.output
    assert "plan" in result.output.lower()
