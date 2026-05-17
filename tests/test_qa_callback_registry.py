from pathlib import Path
from rufino.engine.qa.callback_registry import (
    CallbackRegistry,
    PendingCallback,
)


def test_register_and_retrieve(tmp_path: Path):
    reg = CallbackRegistry(tmp_path / "callbacks.json")
    reg.register(PendingCallback(
        question_slug="q1",
        adapter_name="process-apunte-clase",
        adapter_state={"note_path": "/tmp/n.md"},
    ))

    cb = reg.get("q1")
    assert cb is not None
    assert cb.adapter_name == "process-apunte-clase"
    assert cb.adapter_state["note_path"] == "/tmp/n.md"


def test_persists_across_instances(tmp_path: Path):
    p = tmp_path / "callbacks.json"
    CallbackRegistry(p).register(PendingCallback(
        question_slug="q1", adapter_name="x", adapter_state={},
    ))
    assert CallbackRegistry(p).get("q1") is not None


def test_consume_removes_callback(tmp_path: Path):
    reg = CallbackRegistry(tmp_path / "callbacks.json")
    reg.register(PendingCallback(question_slug="q1", adapter_name="x", adapter_state={}))
    cb = reg.consume("q1")
    assert cb is not None
    assert reg.get("q1") is None  # gone after consume
