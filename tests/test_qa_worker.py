from pathlib import Path
from rufino.engine.qa.api import QALoopAPI
from rufino.engine.qa.worker import poll_and_dispatch


FIXTURE_TEMPLATES = Path(__file__).parent / "fixtures" / "qa-templates"


def test_worker_dispatches_callback_when_answer_present(tmp_vault: Path, tmp_path: Path):
    state = tmp_path / ".rufino-state"
    api = QALoopAPI(
        vault_root=tmp_vault,
        templates_dir=FIXTURE_TEMPLATES,
        state_dir=state,
    )

    q_id = api.ask_user(
        template_name="materia_ambigua",
        context={"apunte_slug": "c", "candidate_materias": [{"slug": "ml-i", "confidence": 70, "reason": "r"}], "evidence": "e"},
        adapter_name="proc-x",
        adapter_state={"note_path": "/tmp/n.md"},
    )

    # User answers
    qf = tmp_vault / "questions" / f"{q_id}.md"
    qf.write_text(qf.read_text().replace("answer:", "answer: ml-i"))

    received: list = []
    def handler(*, adapter_name, adapter_state, answer):
        received.append((adapter_name, adapter_state, answer))

    poll_and_dispatch(
        vault_root=tmp_vault,
        state_dir=state,
        handler=handler,
    )

    assert len(received) == 1
    assert received[0][0] == "proc-x"
    assert received[0][2] == "ml-i"
    # Question moved to answered/
    assert (tmp_vault / "questions" / "answered" / f"{q_id}.md").exists()


def test_worker_skips_pending_questions(tmp_vault: Path, tmp_path: Path):
    state = tmp_path / ".rufino-state"
    api = QALoopAPI(
        vault_root=tmp_vault,
        templates_dir=FIXTURE_TEMPLATES,
        state_dir=state,
    )
    api.ask_user(
        template_name="materia_ambigua",
        context={"apunte_slug": "c", "candidate_materias": [{"slug": "ml-i", "confidence": 70, "reason": "r"}], "evidence": "e"},
        adapter_name="proc-x",
        adapter_state={},
    )

    received: list = []
    poll_and_dispatch(
        vault_root=tmp_vault,
        state_dir=state,
        handler=lambda **kw: received.append(kw),
    )
    assert received == []  # nothing dispatched


def test_worker_marks_answered_before_deleting_callback(tmp_vault: Path, tmp_path: Path, monkeypatch):
    """If `registry.delete` raises after `mark_answered` succeeds, the answer
    must NOT be lost. Worst case is a duplicate dispatch on retry — recoverable.
    The opposite order silently drops the user's answer forever."""
    from rufino.engine.qa.callback_registry import CallbackRegistry

    state = tmp_path / ".rufino-state"
    api = QALoopAPI(
        vault_root=tmp_vault, templates_dir=FIXTURE_TEMPLATES, state_dir=state,
    )
    q_id = api.ask_user(
        template_name="materia_ambigua",
        context={"apunte_slug": "c", "candidate_materias": [{"slug": "ml-i", "confidence": 70, "reason": "r"}], "evidence": "e"},
        adapter_name="proc-x",
        adapter_state={},
    )
    # Simulate user answering.
    q_file = tmp_vault / "questions" / f"{q_id}.md"
    txt = q_file.read_text()
    q_file.write_text(txt.replace("answer:", 'answer: "yes"'))

    # Patch delete to crash.
    real_delete = CallbackRegistry.delete
    def crash_delete(self, slug):
        raise RuntimeError("simulated crash post-mark_answered")
    monkeypatch.setattr(CallbackRegistry, "delete", crash_delete)

    received: list = []
    try:
        poll_and_dispatch(
            vault_root=tmp_vault, state_dir=state,
            handler=lambda **kw: received.append(kw),
        )
    except RuntimeError:
        pass

    # Handler ran (mark_answered must have happened before the crash).
    assert len(received) == 1, "handler did not run"
    # Question is moved to answered/ (mark_answered ran) — recoverable state.
    assert (tmp_vault / "questions" / "answered" / f"{q_id}.md").exists()
    # If we revert and re-run, duplicate dispatch is OK (callback still there).
    monkeypatch.setattr(CallbackRegistry, "delete", real_delete)
