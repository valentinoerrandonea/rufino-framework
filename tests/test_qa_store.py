from pathlib import Path
from rufino.engine.qa.store import (
    QuestionStore,
    Question,
)


def test_write_creates_question_file(tmp_vault: Path):
    qdir = tmp_vault / "questions"
    qdir.mkdir()
    store = QuestionStore(qdir)

    q_id = store.write_question(
        slug="2026-05-16-materia-clase3",
        template_name="materia_ambigua",
        body="¿De qué materia es clase3?",
    )

    q_file = qdir / "2026-05-16-materia-clase3.md"
    assert q_file.exists()
    assert "materia_ambigua" in q_file.read_text()
    assert "answer:" in q_file.read_text()


def test_list_pending_returns_unanswered(tmp_vault: Path):
    qdir = tmp_vault / "questions"
    qdir.mkdir()
    store = QuestionStore(qdir)

    store.write_question(slug="q1", template_name="t", body="b1")
    store.write_question(slug="q2", template_name="t", body="b2")

    # Answer q1
    (qdir / "q1.md").write_text(
        (qdir / "q1.md").read_text().replace("answer:", "answer: ml-i")
    )

    pending = store.list_pending()
    pending_slugs = [q.slug for q in pending]
    assert "q1" not in pending_slugs
    assert "q2" in pending_slugs


def test_get_answer_returns_string(tmp_vault: Path):
    qdir = tmp_vault / "questions"
    qdir.mkdir()
    store = QuestionStore(qdir)
    store.write_question(slug="q1", template_name="t", body="b")
    (qdir / "q1.md").write_text(
        (qdir / "q1.md").read_text().replace("answer:", "answer: ml-i")
    )
    assert store.get_answer("q1") == "ml-i"


def test_get_answer_returns_none_when_unanswered(tmp_vault: Path):
    qdir = tmp_vault / "questions"
    qdir.mkdir()
    store = QuestionStore(qdir)
    store.write_question(slug="q1", template_name="t", body="b")
    assert store.get_answer("q1") is None


def test_mark_answered_moves_file(tmp_vault: Path):
    qdir = tmp_vault / "questions"
    qdir.mkdir()
    store = QuestionStore(qdir)
    store.write_question(slug="q1", template_name="t", body="b")

    store.mark_answered("q1")

    assert not (qdir / "q1.md").exists()
    assert (qdir / "answered" / "q1.md").exists()
