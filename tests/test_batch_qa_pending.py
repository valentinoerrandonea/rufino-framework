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


def test_write_questions_rejects_traversal_in_pending_note(tmp_path, caplog):
    vault = tmp_path / "vault"
    pendings = [PendingQA(
        origin="process-batch", run_id="r1", worker_id="w001",
        pending_note="../escape", input_path="inbox/g/x.md",
        trigger="t", context="c", question="?",
    )]
    with caplog.at_level(logging.WARNING, logger="rufino.engine.process.batch.qa_pending"):
        result = write_questions_to_vault(pendings, vault)
    # Per-item degrade: bad slug logs + appends to failed[], doesn't abort.
    assert result.written == ()
    assert len(result.failed) == 1
    assert any("escape" in r.message for r in caplog.records)


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


def _pq(**overrides) -> PendingQA:
    """Build a PendingQA with sensible defaults, override as needed."""
    base = dict(
        origin="process-batch",
        run_id="r1",
        worker_id="w001",
        pending_note="n1",
        input_path="inbox/g/n1.md",
        trigger="t",
        context="c",
        question="?",
    )
    base.update(overrides)
    return PendingQA(**base)


def test_write_questions_continues_after_invalid_slug(tmp_path):
    """H1: a single bad slug must not abort the whole batch."""
    vault = tmp_path / "vault"
    pending = [
        _pq(pending_note="bad/../escape"),
        _pq(pending_note="good"),
    ]
    result = write_questions_to_vault(pending, vault)

    assert (vault / "questions" / "r1-w001-good.md").exists()
    assert len(result.failed) == 1
    assert "escape" in str(result.failed[0])
    assert len(result.written) == 1


def test_existing_answer_filled_does_not_crash_on_bad_frontmatter(tmp_path):
    """H2: corrupted YAML in an existing question file is treated as not-filled."""
    vault = tmp_path / "vault"
    qdir = vault / "questions"
    qdir.mkdir(parents=True)
    existing = qdir / "r1-w001-x.md"
    existing.write_text("---\nfoo: : :\n---\nanswer: stuff\n", encoding="utf-8")

    pendings = [_pq(pending_note="x")]
    # Must not raise; bad YAML => treat as not-filled => overwrite is allowed.
    result = write_questions_to_vault(pendings, vault)
    assert len(result.written) == 1


def test_answer_detection_uses_frontmatter_not_body_substring(tmp_path):
    """M1: a question whose body contains a line starting with 'answer:' is not filled.

    The frontmatter `answer` field is empty; the body merely *mentions* answer
    on a line that starts with the substring. Body-substring detection would
    incorrectly mark this as filled; frontmatter detection sees the empty
    answer and lets us overwrite.
    """
    vault = tmp_path / "vault"
    qdir = vault / "questions"
    qdir.mkdir(parents=True)
    existing = qdir / "r1-w001-x.md"
    existing.write_text(
        "---\norigin: process-batch\npending_note: x\nanswer: \n---\n"
        "# Question\n\nanswer: this-is-quoted-text-in-the-body-not-an-answer\n",
        encoding="utf-8",
    )

    pendings = [_pq(pending_note="x")]
    result = write_questions_to_vault(pendings, vault)
    # Body line starts with "answer:" but frontmatter['answer'] is empty.
    # Frontmatter-based detection should overwrite.
    assert result.skipped == ()
    assert len(result.written) == 1


def test_collect_pending_rejects_non_string_pending_note(tmp_path, caplog):
    """M6: an LLM emitting a numeric pending_note is rejected cleanly."""
    workers = tmp_path / "workers" / "w001" / "pending"
    workers.mkdir(parents=True)
    (workers / "x.json").write_text(json.dumps({
        "origin": "process-batch", "run_id": "r1", "worker_id": "w001",
        "pending_note": 42, "input_path": "inbox/g/x.md",
        "trigger": "t", "context": "c", "question": "?",
    }), encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="rufino.engine.process.batch.qa_pending"):
        result = collect_pending(tmp_path)
    assert result == []  # rejected silently; no TypeError
    assert any("pending_note" in r.message for r in caplog.records)


def test_question_writes_are_atomic(tmp_path, monkeypatch):
    """M2: writes go through tmp + replace, not direct write_text."""
    vault = tmp_path / "vault"
    (vault / "questions").mkdir(parents=True)
    captured: list[Path] = []
    orig_replace = Path.replace

    def spy_replace(self, target):
        captured.append(Path(target))
        return orig_replace(self, target)

    monkeypatch.setattr(Path, "replace", spy_replace)
    pendings = [_pq(pending_note="x")]
    write_questions_to_vault(pendings, vault)
    # At least one atomic replace happened, targeting the question file.
    assert captured
    assert any(p.name == "r1-w001-x.md" for p in captured)
