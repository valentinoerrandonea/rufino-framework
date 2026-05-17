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
