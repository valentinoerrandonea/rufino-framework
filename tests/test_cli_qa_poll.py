from pathlib import Path
from click.testing import CliRunner
from rufino.cli import cli


def test_qa_poll_cli_runs_with_no_pending(tmp_vault: Path, tmp_path: Path):
    runner = CliRunner()
    result = runner.invoke(cli, [
        "qa-poll",
        "--vault", str(tmp_vault),
        "--state-dir", str(tmp_path / ".rufino-state"),
    ])
    assert result.exit_code == 0
    assert "dispatched=0" in result.output


def test_qa_poll_cli_surfaces_structural_failures(tmp_vault: Path, tmp_path: Path):
    """When .error sidecars exist with a live `.md` sibling (qa_resume wrote
    them on structural fail), the CLI must surface them — count + per-question
    detail — and exit non-zero."""
    qd = tmp_vault / "questions"
    qd.mkdir(parents=True, exist_ok=True)
    # The .md sibling is required — orphan .error files get cleaned up
    # silently instead of firing forever.
    (qd / "r1-w0001-n1.md").write_text(
        "---\norigin: process-batch\n---\n", encoding="utf-8",
    )
    (qd / "r1-w0001-n1.md.error").write_text(
        "ValueError: plan path escapes vault\n", encoding="utf-8",
    )
    runner = CliRunner()
    result = runner.invoke(cli, [
        "qa-poll",
        "--vault", str(tmp_vault),
        "--state-dir", str(tmp_path / ".rufino-state"),
    ])
    assert result.exit_code == 1
    combined = result.output + (result.stderr if result.stderr_bytes else "")
    assert "structural_failures=1" in combined
    assert "plan path escapes vault" in combined


def test_qa_poll_cli_cleans_up_orphan_error_files(tmp_vault: Path, tmp_path: Path):
    """An .error file without a sibling .md (orphan from a kill between
    unlink + move, or manual question deletion) must not fire structural
    failure on every tick — it gets cleaned up silently."""
    qd = tmp_vault / "questions"
    qd.mkdir(parents=True, exist_ok=True)
    orphan = qd / "r1-w0001-old.md.error"
    orphan.write_text("stale\n", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(cli, [
        "qa-poll",
        "--vault", str(tmp_vault),
        "--state-dir", str(tmp_path / ".rufino-state"),
    ])
    assert result.exit_code == 0
    assert "structural_failures" not in result.output
    assert not orphan.exists()


def test_qa_poll_cli_does_not_consume_non_batch_question(tmp_vault: Path, tmp_path: Path):
    """qa-poll only resumes process-batch questions. Legacy QALoopAPI questions
    (origin != 'process-batch') stay in `questions/` untouched, callback intact."""
    from rufino.engine.qa.api import QALoopAPI
    from rufino.engine.qa.callback_registry import CallbackRegistry

    state_dir = tmp_path / ".rufino-state"
    templates_dir = Path(__file__).parent / "fixtures" / "qa-templates"
    api = QALoopAPI(
        vault_root=tmp_vault, templates_dir=templates_dir, state_dir=state_dir,
    )
    q_id = api.ask_user(
        template_name="materia_ambigua",
        context={"apunte_slug": "c", "candidate_materias": [{"slug": "x", "confidence": 70, "reason": "r"}], "evidence": "e"},
        adapter_name="adapter",
        adapter_state={"x": 1},
    )
    q_file = tmp_vault / "questions" / f"{q_id}.md"
    q_file.write_text(q_file.read_text().replace("answer:", 'answer: "x"'))

    result = CliRunner().invoke(cli, [
        "qa-poll", "--vault", str(tmp_vault), "--state-dir", str(state_dir),
    ])
    assert result.exit_code == 0, result.output
    assert "dispatched=0" in result.output
    registry = CallbackRegistry(state_dir / "callbacks.json")
    assert registry.get(q_id) is not None
    assert q_file.exists()
    assert not (tmp_vault / "questions" / "answered" / f"{q_id}.md").exists()
