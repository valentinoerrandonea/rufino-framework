"""CLI smoke test for `rufino process-batch`.

Uses --dry-run so no real claude subprocess is launched; we only verify
the wiring (option parsing, runner invocation, exit code, and output
includes the plan path).
"""
import os
from pathlib import Path

from click.testing import CliRunner

from rufino.cli import cli


FAKE_DIR = Path(__file__).parent / "fixtures" / "fake_claude"


def _make_adapter(tmp: Path) -> Path:
    adapter = tmp / "adapter"
    adapter.mkdir()
    (adapter / "manifest.yaml").write_text("""
adapter_name: x
note_type: x
applies_when: {source_dir: inbox/, matches_pattern: ["*.md"]}
llm: sonnet
mode_default: full
output_schema: {required: {title: string, materia: string}}
triple_vocabulary: [tema-de]
tag_axes: [{axis: materia, format: "materia/{slug}"}]
destination_path: "apuntes/{slug}.md"
""")
    (adapter / "prompt.md").write_text("# adapter prompt\n")
    return adapter


def test_process_batch_dry_run(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(FAKE_DIR.resolve()) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "augment")
    adapter = _make_adapter(tmp_path)
    source = tmp_path / "corpus"
    (source / "math").mkdir(parents=True)
    (source / "math" / "n1.md").write_text("# n\n")
    vault = tmp_path / "vault"

    runner = CliRunner()
    result = runner.invoke(cli, [
        "process-batch", str(source),
        "--adapter", str(adapter),
        "--vault", str(vault),
        "--dry-run",
    ])
    assert result.exit_code == 0, result.output
    assert "plan" in result.output.lower()
