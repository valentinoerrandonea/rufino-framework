from click.testing import CliRunner
from rufino.cli import cli


def test_version_command():
    runner = CliRunner()
    result = runner.invoke(cli, ["version"])
    assert result.exit_code == 0
    assert "0.0.1" in result.output


def test_help_lists_version():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "version" in result.output
