import json
import os
from pathlib import Path

from click.testing import CliRunner

from rufino.cli import cli


FAKE_DIR = Path("tests/fixtures/fake_claude").resolve()


def _setup_pending_question(vault: Path, run_id: str = "r1") -> Path:
    qd = vault / "questions"
    qd.mkdir(parents=True)
    qf = qd / f"{run_id}-w001-n1.md"
    qf.write_text(
        "---\n"
        "origin: process-batch\n"
        f"run_id: {run_id}\n"
        "worker_id: w001\n"
        "pending_note: n1\n"
        "input_path: inbox/g/n1.md\n"
        "trigger: ambig\n"
        "context: c\n"
        "---\n\n"
        "# What is the materia?\n\n"
        "answer: math 101\n"
    )
    return qf


def _setup_run_dir(vault: Path, run_id: str = "r1") -> Path:
    rd = vault / ".rufino" / "runs" / run_id
    (rd / "inbox" / "g").mkdir(parents=True)
    (rd / "inbox" / "g" / "n1.md").write_text("# n\n")
    (rd / "workers" / "w001" / "pending").mkdir(parents=True)
    (rd / "plan.json").write_text(json.dumps({
        "run_id": run_id,
        "adapter_dir": str(rd.parent.parent.parent / "_adapter"),
        "workers": [],
    }))
    return rd


def _setup_adapter(vault: Path) -> Path:
    a = vault / ".rufino" / "runs" / "_adapter"
    a.mkdir(parents=True)
    (a / "manifest.yaml").write_text("""
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
    (a / "prompt.md").write_text("# p\n")
    return a


def test_qa_poll_archives_answered_question(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(FAKE_DIR) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "augment")

    vault = tmp_path / "vault"
    state = tmp_path / "state"
    (vault / "_meta").mkdir(parents=True)
    (vault / "_meta" / "_tags.md").write_text("")
    state.mkdir()

    _setup_adapter(vault)
    _setup_run_dir(vault)
    qf = _setup_pending_question(vault)
    plan_path = vault / ".rufino" / "runs" / "r1" / "plan.json"
    data = json.loads(plan_path.read_text())
    data["adapter_dir"] = str(vault / ".rufino" / "runs" / "_adapter")
    plan_path.write_text(json.dumps(data))

    runner = CliRunner()
    result = runner.invoke(cli, [
        "qa-poll", "--vault", str(vault), "--state-dir", str(state),
    ])
    assert result.exit_code == 0, result.output
    assert not qf.exists()
    archived = vault / "questions" / "answered" / qf.name
    assert archived.exists()
