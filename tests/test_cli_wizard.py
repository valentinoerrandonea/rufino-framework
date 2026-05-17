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


def test_bootstrap_cli_errors_when_claude_binary_missing(monkeypatch):
    import shutil
    monkeypatch.setattr(shutil, "which", lambda _: None)
    runner = CliRunner()
    result = runner.invoke(cli, ["bootstrap"])
    assert result.exit_code != 0
    assert "claude" in result.output.lower()


def test_materialize_cli_expands_tilde_in_paths(tmp_path: Path, monkeypatch):
    """--vault ~ and similar should expand, not be treated as a literal '~' dir."""
    monkeypatch.setenv("HOME", str(tmp_path))
    spec = {
        "vertical_name": "smoke",
        "patterns": ["long_documents_extraction"],
        "entities": ["doc"],
        "sources": [],
        "processing": [],
        "outputs": [],
        "vocabulary": {"doc": "docs/<slug>.md"},
    }
    import json
    spec_file = tmp_path / "spec.json"
    spec_file.write_text(json.dumps(spec))

    runner = CliRunner()
    result = runner.invoke(cli, [
        "materialize",
        "--spec", str(spec_file),
        "--vault", "~/vault",
        "--claude-home", "~/.claude",
        "--state-dir", "~/.rufino-state",
    ])
    assert result.exit_code == 0, result.output
    # Tilde expanded -> created under tmp_path (the fake HOME), not literal "~"
    assert (tmp_path / "vault" / "perfil.md").exists()
    assert not (tmp_path / "~").exists()
