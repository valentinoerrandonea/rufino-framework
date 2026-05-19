import asyncio
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from rufino.cli import cli


@pytest.fixture(autouse=True)
def _path_with_fake_claude(fake_claude_on_path):
    """Autouse delegate to shared conftest fixture (FAKE_CLAUDE_DIR on PATH)."""
    yield


_ADAPTER_MANIFEST = """
adapter_name: x
note_type: x
applies_when: {source_dir: inbox/, matches_pattern: ["*.md"]}
llm: sonnet
mode_default: full
output_schema: {required: {title: string, materia: string}}
triple_vocabulary: [tema-de]
tag_axes: [{axis: materia, format: "materia/{slug}"}]
destination_path: "apuntes/{slug}.md"
"""


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
    (a / "manifest.yaml").write_text(_ADAPTER_MANIFEST)
    (a / "prompt.md").write_text("# p\n")
    return a


def _seed_pending_qa(tmp_path: Path, run_id: str = "r1") -> tuple[Path, Path, Path]:
    """Build a vault + run-dir + adapter + answered question file.

    Returns ``(vault, run_dir, question_file)``. The question file has
    ``answer: "sí"`` in the frontmatter (post-T5 layout).
    """
    vault = tmp_path / "vault"
    (vault / "_meta").mkdir(parents=True)
    (vault / "_meta" / "_tags.md").write_text("")

    adapter = _setup_adapter(vault)
    run_dir = _setup_run_dir(vault, run_id)
    # Adapter path is fixed up to be absolute (matches the path the wizard
    # would have recorded).
    plan_path = run_dir / "plan.json"
    data = json.loads(plan_path.read_text())
    data["adapter_dir"] = str(adapter)
    plan_path.write_text(json.dumps(data))

    qd = vault / "questions"
    qd.mkdir(parents=True, exist_ok=True)
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
        'answer: "sí"\n'
        "---\n\n"
        "# What is the materia?\n",
        encoding="utf-8",
    )
    return vault, run_dir, qf


def test_qa_poll_archives_answered_question(tmp_path, monkeypatch):
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


def test_qa_resume_lands_note_in_vault_canon(tmp_path, monkeypatch):
    """C1: after qa-poll, the augmented note must exist at destination_path."""
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "augment")
    vault, run_dir, question_file = _seed_pending_qa(tmp_path)

    from rufino.engine.process.batch.qa_resume import resume_pending_qa
    ok = asyncio.run(
        resume_pending_qa(vault_root=vault, question_file=question_file)
    )

    assert ok is True
    # The destination_path template in _seed_pending_qa is "apuntes/{slug}.md"
    assert (vault / "apuntes" / "n1.md").exists()
    assert (vault / "apuntes" / "n1.md").read_text(encoding="utf-8").startswith("---")


def test_qa_resume_rejects_malicious_run_id(tmp_path):
    """C2 claude: run_id with path-traversal is rejected before any I/O."""
    vault = tmp_path / "vault"
    (vault / "questions").mkdir(parents=True)
    qfile = vault / "questions" / "q1.md"
    qfile.write_text(
        "---\n"
        "origin: process-batch\n"
        "run_id: ../../../etc\n"
        "worker_id: w001\n"
        "pending_note: x\n"
        "trigger: t\n"
        "context: c\n"
        "---\n"
        "answer: sí\n",
        encoding="utf-8",
    )

    from rufino.engine.process.batch.qa_resume import resume_pending_qa
    from rufino.engine.process.batch.errors import BatchError
    with pytest.raises(BatchError, match="unsafe identifier"):
        asyncio.run(
            resume_pending_qa(vault_root=vault, question_file=qfile)
        )


@pytest.mark.parametrize("field,value", [
    ("run_id", ".."),
    ("worker_id", ".."),
    ("pending_note", ".."),
    ("pending_note", "."),
])
def test_qa_resume_rejects_pure_dot_identifiers(tmp_path, field, value):
    """``..`` and ``.`` match [A-Za-z0-9._-]+ but walk the filesystem when
    joined into a path. _assert_safe_id must reject them explicitly."""
    vault = tmp_path / "vault"
    (vault / "questions").mkdir(parents=True)
    qfile = vault / "questions" / "q1.md"
    fm = {
        "origin": "process-batch",
        "run_id": "valid-run",
        "worker_id": "w001",
        "pending_note": "valid",
        "trigger": "t",
        "context": "c",
    }
    fm[field] = value
    lines = ["---"]
    lines.extend(f"{k}: {v!r}" for k, v in fm.items())
    lines.extend(["---", 'answer: "sí"', ""])
    qfile.write_text("\n".join(lines), encoding="utf-8")

    from rufino.engine.process.batch.qa_resume import resume_pending_qa
    from rufino.engine.process.batch.errors import BatchError
    with pytest.raises(BatchError, match="unsafe identifier"):
        asyncio.run(
            resume_pending_qa(vault_root=vault, question_file=qfile)
        )


def test_qa_resume_rejects_malicious_worker_id(tmp_path):
    """Same as above but the path-traversal lives in worker_id."""
    vault = tmp_path / "vault"
    (vault / "questions").mkdir(parents=True)
    qfile = vault / "questions" / "q1.md"
    qfile.write_text(
        "---\n"
        "origin: process-batch\n"
        "run_id: 2026-05-19T00-00-00Z-abcdef\n"
        "worker_id: ../escape\n"
        "pending_note: x\n"
        "trigger: t\n"
        "context: c\n"
        "---\n"
        "answer: sí\n",
        encoding="utf-8",
    )

    from rufino.engine.process.batch.qa_resume import resume_pending_qa
    from rufino.engine.process.batch.errors import BatchError
    with pytest.raises(BatchError, match="unsafe identifier"):
        asyncio.run(
            resume_pending_qa(vault_root=vault, question_file=qfile)
        )


def test_qa_resume_does_not_leak_fake_claude_notes_env(tmp_path, monkeypatch):
    """H4 claude: FAKE_CLAUDE_NOTES must not be set by resume_pending_qa itself."""
    monkeypatch.delenv("FAKE_CLAUDE_NOTES", raising=False)
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "augment")
    vault, run_dir, qfile = _seed_pending_qa(tmp_path)
    captured: dict = {}

    async def fake_run_claude(**kwargs):
        captured["env"] = kwargs["env"]
        from rufino.engine.process.batch.runner_helper import ClaudeResult
        # Simulate that the worker did its job by writing the augmented file
        staging = kwargs["cwd"]
        (staging / "augmented").mkdir(parents=True, exist_ok=True)
        (staging / "augmented" / "n1.md").write_text(
            "---\ntitle: n1\nmateria: fake\n---\n# n1\n", encoding="utf-8")
        (staging / "deltas").mkdir(parents=True, exist_ok=True)
        (staging / "deltas" / "n1.json").write_text(
            json.dumps({
                "note_slug": "n1",
                "tags_added": [],
                "triples_emitted": [],
                "concepts_referenced": [],
                "concepts_promoted": [],
                "wikilinks_added": [],
                "qa_opened": [],
                "warnings": [],
            }),
            encoding="utf-8",
        )
        return ClaudeResult(exit_code=0, stdout="", stderr="")

    monkeypatch.setattr(
        "rufino.engine.process.batch.qa_resume.run_claude", fake_run_claude,
    )
    from rufino.engine.process.batch.qa_resume import resume_pending_qa
    asyncio.run(resume_pending_qa(vault_root=vault, question_file=qfile))

    assert "FAKE_CLAUDE_NOTES" not in captured["env"]
