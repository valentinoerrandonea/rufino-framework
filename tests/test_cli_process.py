from pathlib import Path
from click.testing import CliRunner
from rufino.cli import cli


def test_process_light_via_cli(tmp_vault: Path):
    inbox = tmp_vault / "inbox"
    inbox.mkdir()
    note = inbox / "n.md"
    note.write_text(
        "---\ntags: [materia/ml-i]\n---\nBody\n"
    )
    (tmp_vault / "_meta").mkdir()
    (tmp_vault / "_meta" / "_tags.md").write_text("# Tags\n")
    (tmp_vault / "_meta" / "_processing-log.md").write_text("# Log\n")

    runner = CliRunner()
    result = runner.invoke(cli, [
        "process", str(note),
        "--vault", str(tmp_vault),
        "--mode", "light",
    ])
    assert result.exit_code == 0, result.output
    assert "materia/ml-i" in (tmp_vault / "_meta" / "_tags.md").read_text()
