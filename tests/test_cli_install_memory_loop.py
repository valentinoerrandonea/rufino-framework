from pathlib import Path
from click.testing import CliRunner
from rufino.cli import cli


FIXTURE = Path(__file__).parent / "fixtures" / "adapters" / "memory-loop-facultad"


def test_install_memory_loop_cli(tmp_path: Path, tmp_vault: Path):
    claude_home = tmp_path / ".claude"
    claude_home.mkdir()
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "install-memory-loop",
            str(FIXTURE),
            "--vault", str(tmp_vault),
            "--claude-home", str(claude_home),
        ],
    )

    assert result.exit_code == 0, result.output
    assert (claude_home / "hooks" / "rufino-memory-loop-init.sh").exists()
    assert "installed" in result.output.lower()


def test_install_memory_loop_cli_fails_on_bad_manifest(tmp_path: Path, tmp_vault: Path):
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "manifest.yaml").write_text("vertical_name: x\n")
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "install-memory-loop", str(bad),
            "--vault", str(tmp_vault),
            "--claude-home", str(tmp_path / ".claude"),
        ],
    )
    assert result.exit_code != 0
