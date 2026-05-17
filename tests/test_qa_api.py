from pathlib import Path
from rufino.engine.qa.api import QALoopAPI


FIXTURE_TEMPLATES = Path(__file__).parent / "fixtures" / "qa-templates"


def test_ask_user_creates_question(tmp_vault: Path, tmp_path: Path):
    api = QALoopAPI(
        vault_root=tmp_vault,
        templates_dir=FIXTURE_TEMPLATES,
        state_dir=tmp_path / ".rufino-state",
    )

    q_id = api.ask_user(
        template_name="materia_ambigua",
        context={
            "apunte_slug": "clase3",
            "candidate_materias": [{"slug": "ml-i", "confidence": 70, "reason": "r"}],
            "evidence": "e",
        },
        adapter_name="process-apunte-clase",
        adapter_state={"note_path": "/tmp/n.md"},
    )

    assert q_id.startswith("materia_ambigua-")
    q_file = tmp_vault / "questions" / f"{q_id}.md"
    assert q_file.exists()
    assert "clase3" in q_file.read_text()


def test_get_answer_returns_none_when_pending(tmp_vault: Path, tmp_path: Path):
    api = QALoopAPI(
        vault_root=tmp_vault,
        templates_dir=FIXTURE_TEMPLATES,
        state_dir=tmp_path / ".rufino-state",
    )

    q_id = api.ask_user(
        template_name="materia_ambigua",
        context={
            "apunte_slug": "x",
            "candidate_materias": [{"slug": "a", "confidence": 50, "reason": "r"}],
            "evidence": "e",
        },
        adapter_name="adapter-x",
        adapter_state={},
    )
    assert api.get_answer(q_id) is None
