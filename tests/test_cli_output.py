from pathlib import Path
from click.testing import CliRunner
from rufino.cli import cli


FIXTURE = Path(__file__).parent / "fixtures" / "adapters" / "output-digest-semanal-facultad"


def test_output_cli_runs_adapter(tmp_vault: Path):
    runner = CliRunner()
    result = runner.invoke(cli, [
        "output", str(FIXTURE),
        "--vault", str(tmp_vault),
    ])
    assert result.exit_code == 0, result.output
    out = tmp_vault / "general" / "digests" / "W20.md"
    assert out.exists()
