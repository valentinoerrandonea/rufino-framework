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


def test_output_cli_uses_real_lexical_query(tmp_vault: Path, tmp_path: Path):
    """rufino output must invoke the real lexical query layer (not a stub)
    so manifests with `query:` entries get real results."""
    from click.testing import CliRunner
    from rufino.cli import cli

    (tmp_vault / "note.md").write_text("alpha regresion logistica beta", encoding="utf-8")

    adapter = tmp_path / "adapter"
    adapter.mkdir()
    (adapter / "manifest.yaml").write_text(
        "adapter_name: digest\n"
        "trigger:\n  type: cron\n  expression: '0 8 * * *'\n"
        "query:\n  - {name: hits, expression: 'regresion'}\n"
        "template: template.md\n"
        "delivery:\n  - {channel: file, path: out.md}\n"
    )
    (adapter / "template.md").write_text("{{ query.hits | join('\\n') }}\n")

    res = CliRunner().invoke(cli, ["output", str(adapter), "--vault", str(tmp_vault)])
    assert res.exit_code == 0, res.output
    assert (tmp_vault / "out.md").exists()
    assert "note.md" in (tmp_vault / "out.md").read_text()
