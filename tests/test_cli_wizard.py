import json
from pathlib import Path

from click.testing import CliRunner

from rufino.cli import cli


def test_materialize_cli_from_spec_file(tmp_path: Path):
    spec = {
        "vertical_name": "smoke",
        "patterns": ["long_documents_extraction"],
        "entities": ["doc"],
        "sources": [],
        "processing": [],
        "outputs": [],
        "vocabulary": {"doc": "docs/<slug>.md"},
    }
    spec_file = tmp_path / "spec.json"
    spec_file.write_text(json.dumps(spec))

    runner = CliRunner()
    result = runner.invoke(cli, [
        "materialize",
        "--spec", str(spec_file),
        "--vault", str(tmp_path / "vault"),
        "--claude-home", str(tmp_path / ".claude"),
        "--state-dir", str(tmp_path / ".rufino-state"),
    ])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "vault" / "perfil.md").exists()


def test_materialize_cli_rejects_invalid_spec(tmp_path: Path):
    bad = {"vertical_name": "smoke"}  # missing fields
    spec_file = tmp_path / "spec.json"
    spec_file.write_text(json.dumps(bad))

    runner = CliRunner()
    result = runner.invoke(cli, [
        "materialize",
        "--spec", str(spec_file),
        "--vault", str(tmp_path / "vault"),
        "--claude-home", str(tmp_path / ".claude"),
        "--state-dir", str(tmp_path / ".rufino-state"),
    ])
    assert result.exit_code == 1
    assert "validation" in result.output.lower() or "missing" in result.output.lower()


def test_bootstrap_cli_dry_run_prints_prompt():
    runner = CliRunner()
    result = runner.invoke(cli, ["bootstrap", "--dry-run"])
    assert result.exit_code == 0
    assert "Rufino Framework Wizard" in result.output
