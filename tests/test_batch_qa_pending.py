import json
import logging
from pathlib import Path

import pytest
import yaml

from rufino.engine.process.batch.qa_pending import (
    InvalidPendingSlugError,
    PendingQA,
    WriteResult,
    collect_pending,
    write_questions_to_vault,
)


def _write_pending(staging: Path, slug: str, payload: dict) -> None:
    p = staging / "pending"
    p.mkdir(parents=True, exist_ok=True)
    (p / f"{slug}.json").write_text(json.dumps(payload))


def test_collect_pending_finds_all_across_workers(tmp_path):
    w1 = tmp_path / "workers" / "w001"
    w2 = tmp_path / "workers" / "w002"
    _write_pending(w1, "n1", {
        "origin": "process-batch", "run_id": "r1", "worker_id": "w001",
        "pending_note": "n1", "input_path": "inbox/g/n1.md",
        "trigger": "ambig", "context": "c", "question": "?",
    })
    _write_pending(w2, "n2", {
        "origin": "process-batch", "run_id": "r1", "worker_id": "w002",
        "pending_note": "n2", "input_path": "inbox/g/n2.md",
        "trigger": "ambig", "context": "c", "question": "?",
    })
    pendings = collect_pending(tmp_path)
    assert {p.pending_note for p in pendings} == {"n1", "n2"}


def test_collect_pending_skips_malformed_and_warns(tmp_path, caplog):
    w1 = tmp_path / "workers" / "w001"
    (w1 / "pending").mkdir(parents=True)
    (w1 / "pending" / "broken.json").write_text("{not json")
    with caplog.at_level(logging.WARNING, logger="rufino.engine.process.batch.qa_pending"):
        pendings = collect_pending(tmp_path)
    assert pendings == []
    assert any("broken.json" in r.message for r in caplog.records)


def test_collect_pending_warns_on_missing_required_key(tmp_path, caplog):
    w1 = tmp_path / "workers" / "w001"
    (w1 / "pending").mkdir(parents=True)
    (w1 / "pending" / "incomplete.json").write_text(json.dumps(
        {"origin": "process-batch"}  # missing run_id, worker_id, etc.
    ))
    with caplog.at_level(logging.WARNING, logger="rufino.engine.process.batch.qa_pending"):
        pendings = collect_pending(tmp_path)
    assert pendings == []
    assert any("incomplete.json" in r.message for r in caplog.records)


def test_write_questions_creates_question_files(tmp_path):
    vault = tmp_path / "vault"
    (vault / "questions").mkdir(parents=True)
    pendings = [PendingQA(
        origin="process-batch", run_id="r1", worker_id="w001",
        pending_note="n1", input_path="inbox/g/n1.md",
        trigger="ambig_materia", context="some ctx",
        question="What is the materia?",
    )]
    result = write_questions_to_vault(pendings, vault)
    assert isinstance(result, WriteResult)
    assert len(result.written) == 1
    body = result.written[0].read_text()
    assert "What is the materia?" in body
    assert "answer:" in body
    assert "origin: process-batch" in body
    assert "pending_note: n1" in body
    # YAML must be parseable, not hand-rolled.
    fm_block = body.split("---\n")[1]
    parsed = yaml.safe_load(fm_block)
    assert parsed["origin"] == "process-batch"
    assert parsed["pending_note"] == "n1"
    assert parsed["context"] == "some ctx"


def test_write_questions_yaml_handles_special_chars_in_context(tmp_path):
    vault = tmp_path / "vault"
    pendings = [PendingQA(
        origin="process-batch", run_id="r1", worker_id="w001",
        pending_note="n1", input_path="inbox/g/n1.md",
        trigger="ambig", context="line1: weird #stuff\nline2 'quotes'",
        question="?",
    )]
    result = write_questions_to_vault(pendings, vault)
    body = result.written[0].read_text()
    fm_block = body.split("---\n")[1]
    parsed = yaml.safe_load(fm_block)
    # Round-trip must preserve the exact context, despite colons/quotes/newlines.
    assert parsed["context"] == "line1: weird #stuff\nline2 'quotes'"


def test_write_questions_rejects_traversal_in_pending_note(tmp_path):
    vault = tmp_path / "vault"
    pendings = [PendingQA(
        origin="process-batch", run_id="r1", worker_id="w001",
        pending_note="../escape", input_path="inbox/g/x.md",
        trigger="t", context="c", question="?",
    )]
    with pytest.raises(InvalidPendingSlugError):
        write_questions_to_vault(pendings, vault)


def test_write_questions_skips_existing_with_filled_answer(tmp_path, caplog):
    vault = tmp_path / "vault"
    qdir = vault / "questions"
    qdir.mkdir(parents=True)
    existing = qdir / "r1-w001-n1.md"
    existing.write_text(
        "---\norigin: process-batch\npending_note: n1\n---\n# old?\n\nanswer: yes-already\n"
    )
    pendings = [PendingQA(
        origin="process-batch", run_id="r1", worker_id="w001",
        pending_note="n1", input_path="inbox/g/n1.md",
        trigger="t", context="c", question="?",
    )]
    with caplog.at_level(logging.WARNING, logger="rufino.engine.process.batch.qa_pending"):
        result = write_questions_to_vault(pendings, vault)
    assert result.written == ()
    assert len(result.skipped) == 1
    # Existing answer must NOT be clobbered.
    assert "yes-already" in existing.read_text()
    assert any("yes-already" not in r.message and "n1" in r.message for r in caplog.records)


def test_write_questions_overwrites_existing_with_empty_answer(tmp_path):
    vault = tmp_path / "vault"
    qdir = vault / "questions"
    qdir.mkdir(parents=True)
    existing = qdir / "r1-w001-n1.md"
    existing.write_text(
        "---\norigin: process-batch\npending_note: n1\n---\n# old?\n\nanswer: \n"
    )
    pendings = [PendingQA(
        origin="process-batch", run_id="r1", worker_id="w001",
        pending_note="n1", input_path="inbox/g/n1.md",
        trigger="t", context="new ctx", question="new?",
    )]
    result = write_questions_to_vault(pendings, vault)
    assert len(result.written) == 1
    assert "new ctx" in existing.read_text()
