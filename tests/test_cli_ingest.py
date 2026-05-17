from pathlib import Path
from click.testing import CliRunner
from rufino.cli import cli


FIXTURE = Path(__file__).parent / "fixtures" / "adapters" / "ingest-belo"


def test_ingest_cli_emits_facts(tmp_vault: Path, tmp_path: Path):
    runner = CliRunner()
    result = runner.invoke(cli, [
        "ingest", str(FIXTURE),
        "--vault", str(tmp_vault),
        "--state-dir", str(tmp_path / ".rufino-state"),
    ])
    assert result.exit_code == 0, result.output
    assert "emitted=2" in result.output
