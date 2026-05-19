import json
from pathlib import Path

import pytest

from rufino.engine.process.batch.qa_pending import (
    PendingQA,
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


def test_collect_pending_skips_malformed(tmp_path):
    w1 = tmp_path / "workers" / "w001"
    (w1 / "pending").mkdir(parents=True)
    (w1 / "pending" / "broken.json").write_text("{not json")
    pendings = collect_pending(tmp_path)
    assert pendings == []


def test_write_questions_creates_question_files(tmp_path):
    vault = tmp_path / "vault"
    (vault / "questions").mkdir(parents=True)
    pendings = [PendingQA(
        origin="process-batch", run_id="r1", worker_id="w001",
        pending_note="n1", input_path="inbox/g/n1.md",
        trigger="ambig_materia", context="some ctx",
        question="What is the materia?",
    )]
    written = write_questions_to_vault(pendings, vault)
    assert len(written) == 1
    body = written[0].read_text()
    assert "What is the materia?" in body
    assert "answer:" in body
    assert "origin: process-batch" in body
    assert "pending_note: n1" in body
