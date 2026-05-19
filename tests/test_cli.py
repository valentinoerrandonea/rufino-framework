from click.testing import CliRunner
from rufino.cli import cli


def test_version_command():
    runner = CliRunner()
    result = runner.invoke(cli, ["version"])
    assert result.exit_code == 0
    from rufino.version import VERSION
    assert VERSION in result.output


def test_help_lists_version():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "version" in result.output


def test_noop_embeddings_raises_instead_of_silently_returning_zeros():
    import pytest
    from rufino.cli import _NoopEmbeddings
    with pytest.raises(NotImplementedError, match="placeholder"):
        _NoopEmbeddings().embed("hello")


def test_query_cmd_semantic_mode_exits_non_zero_with_clear_error(tmp_path):
    from click.testing import CliRunner
    from rufino.cli import cli
    vault = tmp_path / "v"
    vault.mkdir()
    res = CliRunner().invoke(cli, ["query", "x", "--vault", str(vault), "--mode", "semantic"])
    assert res.exit_code != 0
    assert "placeholder" in (res.output + (res.stderr or ""))


def test_query_cmd_lexical_mode_works_without_embedder(tmp_path):
    from click.testing import CliRunner
    from rufino.cli import cli
    vault = tmp_path / "v"
    vault.mkdir()
    (vault / "x.md").write_text("hello world")
    res = CliRunner().invoke(cli, ["query", "hello", "--vault", str(vault), "--mode", "lexical"])
    assert res.exit_code == 0, res.output


def test_materialize_registers_mcp_server(tmp_path, monkeypatch):
    """rufino materialize must write ~/.claude.json with a per-vault MCP entry
    pointing at the new vault."""
    import json
    from click.testing import CliRunner
    from rufino.cli import cli
    from rufino.runtime.vault_slug import compute_vault_slug

    monkeypatch.setenv("HOME", str(tmp_path))
    # Path.home() reads HOME on POSIX but in modern Python uses pwd; monkeypatch.
    monkeypatch.setattr("pathlib.Path.home", classmethod(lambda cls: tmp_path))

    spec = {
        "vertical_name": "t",
        "patterns": [],
        "entities": ["note"],
        "vocabulary": {"note": "notes/<slug>.md"},
        "sources": [],
        "processing": [],
        "outputs": [],
    }
    spec_file = tmp_path / "spec.json"
    spec_file.write_text(json.dumps(spec))

    vault = tmp_path / "vault"
    res = CliRunner().invoke(cli, [
        "materialize",
        "--spec", str(spec_file),
        "--vault", str(vault),
        "--claude-home", str(tmp_path / ".claude_home"),
        "--state-dir", str(tmp_path / ".state"),
    ])
    assert res.exit_code == 0, res.output

    cfg = json.loads((tmp_path / ".claude.json").read_text())
    entry = cfg["mcpServers"][f"ask-rufino-{compute_vault_slug(vault)}"]
    assert entry["args"][0] == "mcp-server"
    assert entry["args"][1] == "--vault"
    assert entry["args"][2] == str(vault)
