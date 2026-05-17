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


def test_qa_poll_cli_does_not_consume_when_resumption_unimplemented(tmp_vault: Path, tmp_path: Path):
    """If a pending answer exists, qa-poll must exit non-zero and leave the
    callback + question in place (so a real handler can later resume)."""
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
    # Simulate user answering.
    q_file = tmp_vault / "questions" / f"{q_id}.md"
    q_file.write_text(q_file.read_text().replace("answer:", 'answer: "x"'))

    result = CliRunner().invoke(cli, [
        "qa-poll", "--vault", str(tmp_vault), "--state-dir", str(state_dir),
    ])
    assert result.exit_code != 0, result.output
    # Callback must still be there for a real handler later.
    registry = CallbackRegistry(state_dir / "callbacks.json")
    assert registry.get(q_id) is not None
    # Question file must still be in `questions/`, not archived.
    assert q_file.exists()
    assert not (tmp_vault / "questions" / "answered" / f"{q_id}.md").exists()
