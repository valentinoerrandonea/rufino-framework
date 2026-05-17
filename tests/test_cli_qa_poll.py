from pathlib import Path
from click.testing import CliRunner
from rufino.cli import cli


def test_qa_poll_cli_runs_with_no_pending(tmp_vault: Path, tmp_path: Path):
    runner = CliRunner()
    result = runner.invoke(cli, [
        "qa-poll",
        "--vault", str(tmp_vault),
        "--state-dir", str(tmp_path / ".rufino-state"),
    ])
    assert result.exit_code == 0
    assert "dispatched=0" in result.output
