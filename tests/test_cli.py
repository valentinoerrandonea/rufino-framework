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
