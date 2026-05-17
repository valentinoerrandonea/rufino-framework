"""Tests for the security/atomicity/crash-resilience fixes applied after
the first-pass code review of Plan 6 (Q&A loop primitive).
"""
import json
from pathlib import Path

import pytest

from rufino.engine.qa.api import QALoopAPI, QALoopError
from rufino.engine.qa.callback_registry import (
    CallbackRegistry,
    CallbackRegistryError,
    PendingCallback,
)
from rufino.engine.qa.store import QuestionStore, QuestionStoreError
from rufino.engine.qa.worker import poll_and_dispatch


FIXTURE_TEMPLATES = Path(__file__).parent / "fixtures" / "qa-templates"


# ---------------------------------------------------------------------------
# C1: template_name path traversal
# ---------------------------------------------------------------------------

def test_ask_user_rejects_template_name_path_traversal(tmp_vault: Path, tmp_path: Path):
    api = QALoopAPI(
        vault_root=tmp_vault,
        templates_dir=FIXTURE_TEMPLATES,
        state_dir=tmp_path / "state",
    )
    with pytest.raises(QALoopError, match="escapes templates_dir"):
        api.ask_user(
            template_name="../../etc/passwd",
            context={},
            adapter_name="x",
            adapter_state={},
        )


# ---------------------------------------------------------------------------
# C2: store slug path traversal
# ---------------------------------------------------------------------------

def test_store_rejects_slug_escaping_questions_dir(tmp_vault: Path):
    qdir = tmp_vault / "questions"
    store = QuestionStore(qdir)
    with pytest.raises(QuestionStoreError, match="escapes"):
        store.write_question(slug="../escape", template_name="t", body="b")
    with pytest.raises(QuestionStoreError, match="escapes"):
        store.get_answer("../escape")
    with pytest.raises(QuestionStoreError, match="escapes"):
        store.mark_answered("../escape")


# ---------------------------------------------------------------------------
# C3: atomic flush + corruption detection
# ---------------------------------------------------------------------------

def test_callback_registry_uses_atomic_write(tmp_path: Path):
    path = tmp_path / "callbacks.json"
    reg = CallbackRegistry(path)
    reg.register(PendingCallback(question_slug="q1", adapter_name="a", adapter_state={}))
    # No leftover .tmp after successful write
    assert not path.with_suffix(path.suffix + ".tmp").exists()


def test_callback_registry_raises_on_corrupt_file(tmp_path: Path):
    path = tmp_path / "callbacks.json"
    path.write_text("not valid json {{{")
    with pytest.raises(CallbackRegistryError, match="corrupt"):
        CallbackRegistry(path)


# ---------------------------------------------------------------------------
# I2: YAML bareword answers rejected
# ---------------------------------------------------------------------------

def test_get_answer_rejects_yaml_bareword_bool(tmp_vault: Path):
    qdir = tmp_vault / "questions"
    store = QuestionStore(qdir)
    store.write_question(slug="q1", template_name="t", body="b")
    # User typed `yes` without quotes — YAML parses it as True.
    qf = qdir / "q1.md"
    qf.write_text(qf.read_text().replace("answer:", "answer: yes"))
    with pytest.raises(QuestionStoreError, match="wrap the value in quotes"):
        store.get_answer("q1")


def test_get_answer_accepts_quoted_yes(tmp_vault: Path):
    qdir = tmp_vault / "questions"
    store = QuestionStore(qdir)
    store.write_question(slug="q1", template_name="t", body="b")
    qf = qdir / "q1.md"
    qf.write_text(qf.read_text().replace("answer:", 'answer: "yes"'))
    assert store.get_answer("q1") == "yes"


# ---------------------------------------------------------------------------
# I3: worker handler crash leaves callback + question intact
# ---------------------------------------------------------------------------

def test_worker_preserves_state_when_handler_raises(tmp_vault: Path, tmp_path: Path):
    state = tmp_path / "state"
    api = QALoopAPI(
        vault_root=tmp_vault,
        templates_dir=FIXTURE_TEMPLATES,
        state_dir=state,
    )
    q_id = api.ask_user(
        template_name="materia_ambigua",
        context={
            "apunte_slug": "c",
            "candidate_materias": [{"slug": "ml-i", "confidence": 70, "reason": "r"}],
            "evidence": "e",
        },
        adapter_name="proc-x",
        adapter_state={"k": "v"},
    )
    qf = tmp_vault / "questions" / f"{q_id}.md"
    qf.write_text(qf.read_text().replace("answer:", "answer: ml-i"))

    def crashing_handler(**kw):
        raise RuntimeError("boom")

    dispatched = poll_and_dispatch(
        vault_root=tmp_vault, state_dir=state, handler=crashing_handler
    )
    assert dispatched == 0
    # Question file still in pending location
    assert qf.exists()
    assert not (tmp_vault / "questions" / "answered" / f"{q_id}.md").exists()
    # Callback still registered for retry
    reg = CallbackRegistry(state / "callbacks.json")
    assert reg.get(q_id) is not None


# ---------------------------------------------------------------------------
# I4: hand-rolled frontmatter escapes template_name with YAML specials
# ---------------------------------------------------------------------------

def test_question_file_escapes_yaml_special_template_name(tmp_vault: Path):
    qdir = tmp_vault / "questions"
    store = QuestionStore(qdir)
    # template_name with a colon would corrupt naive frontmatter
    store.write_question(
        slug="q1", template_name="weird: name", body="b"
    )
    # Re-parse — should round-trip cleanly via parse_frontmatter
    pending = store.list_pending()
    assert len(pending) == 1
    assert pending[0].template_name == "weird: name"


# ---------------------------------------------------------------------------
# I5: PendingCallback.adapter_state is isolated from caller mutations
# ---------------------------------------------------------------------------

def test_callback_state_isolated_from_caller_mutation(tmp_path: Path):
    reg = CallbackRegistry(tmp_path / "callbacks.json")
    state = {"k": "v"}
    reg.register(PendingCallback(question_slug="q1", adapter_name="a", adapter_state=state))
    state["k"] = "mutated"  # caller mutates after register
    cb = reg.get("q1")
    assert cb.adapter_state["k"] == "v"  # registry view unchanged


def test_callback_state_is_readonly_view(tmp_path: Path):
    reg = CallbackRegistry(tmp_path / "callbacks.json")
    reg.register(PendingCallback(question_slug="q1", adapter_name="a", adapter_state={"k": "v"}))
    cb = reg.get("q1")
    with pytest.raises(TypeError):
        cb.adapter_state["k"] = "x"  # MappingProxyType is read-only


# ---------------------------------------------------------------------------
# I1: CRLF-formatted question files still parse
# ---------------------------------------------------------------------------

def test_get_answer_handles_crlf_question_file(tmp_vault: Path):
    qdir = tmp_vault / "questions"
    store = QuestionStore(qdir)
    store.write_question(slug="q1", template_name="t", body="b")
    qf = qdir / "q1.md"
    # Simulate Obsidian-on-Windows saving with CRLF line endings
    crlf = qf.read_text().replace("\n", "\r\n").replace("answer:", "answer: hola")
    qf.write_bytes(crlf.encode())
    assert store.get_answer("q1") == "hola"


# ---------------------------------------------------------------------------
# Worker: warns (doesn't crash) when answered question has no callback
# ---------------------------------------------------------------------------

def test_worker_skips_answered_without_callback(tmp_vault: Path, tmp_path: Path):
    state = tmp_path / "state"
    api = QALoopAPI(
        vault_root=tmp_vault,
        templates_dir=FIXTURE_TEMPLATES,
        state_dir=state,
    )
    q_id = api.ask_user(
        template_name="materia_ambigua",
        context={
            "apunte_slug": "c",
            "candidate_materias": [{"slug": "ml-i", "confidence": 70, "reason": "r"}],
            "evidence": "e",
        },
        adapter_name="proc-x",
        adapter_state={},
    )
    # Manually delete the callback (simulates orphaned answer)
    reg = CallbackRegistry(state / "callbacks.json")
    reg.consume(q_id)

    qf = tmp_vault / "questions" / f"{q_id}.md"
    qf.write_text(qf.read_text().replace("answer:", "answer: ml-i"))

    received: list = []
    dispatched = poll_and_dispatch(
        vault_root=tmp_vault, state_dir=state,
        handler=lambda **kw: received.append(kw),
    )
    assert dispatched == 0
    assert received == []
    # File still pending (we didn't move it)
    assert qf.exists()
