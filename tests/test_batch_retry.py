import asyncio
import json
import logging
from pathlib import Path

import pytest

from rufino.engine.process.batch.planner import WorkerAssignment
from rufino.engine.process.batch.retry import retry_failed
from rufino.engine.process.batch.validator import NoteValidation, ValidationReport
from rufino.engine.process.manifest import parse_worker_manifest


_MANIFEST = """
adapter_name: x
note_type: x
applies_when: {source_dir: inbox/, matches_pattern: ["*.md"]}
llm: sonnet
mode_default: full
output_schema:
  required:
    title: string
    materia: string
triple_vocabulary:
  - tema-de
tag_axes:
  - axis: materia
    format: "materia/{slug}"
destination_path: "x/{slug}.md"
"""


@pytest.fixture(autouse=True)
def _fake_claude_on_path(fake_claude_on_path):
    """Autouse delegate to shared conftest fixture (FAKE_CLAUDE_DIR on PATH)."""
    yield


def _setup_failed_note(staging: Path, slug: str) -> NoteValidation:
    aug = staging / "augmented" / f"{slug}.md"
    aug.parent.mkdir(parents=True, exist_ok=True)
    aug.write_text("---\nmateria: x\n---\n# body\n")
    return NoteValidation(
        slug=slug, augmented_path=aug, delta_path=None,
        errors=("schema violation: missing 'title'",),
    )


def _write_canonical_assignment(
    staging: Path, *, run_id: str, worker_id: str, group: str, notes: tuple[Path, ...],
) -> dict:
    staging.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": run_id, "worker_id": worker_id, "group": group,
        "notes": [str(p) for p in notes],
    }
    (staging / "assignment.json").write_text(json.dumps(payload, indent=2))
    return payload


def test_retry_succeeds_on_second_try(tmp_path, monkeypatch):
    manifest = parse_worker_manifest(_MANIFEST)
    note = tmp_path / "inbox" / "g" / "n1.md"
    note.parent.mkdir(parents=True)
    note.write_text("# n\n")
    staging = tmp_path / "workers" / "w0001"
    failed = (_setup_failed_note(staging, "n1"),)
    canonical = _write_canonical_assignment(
        staging, run_id=tmp_path.name, worker_id="w0001", group="g", notes=(note,),
    )

    monkeypatch.setenv("FAKE_CLAUDE_MODE", "augment")

    report = asyncio.run(retry_failed(
        failed=failed, manifest=manifest, adapter_prompt_text="",
        worker_assignment=WorkerAssignment(worker_id="w0001", group="g", notes=(note,)),
        run_dir=tmp_path, vault_slug="v",
        max_retries=2, timeout_seconds=30,
    ))
    assert len(report.passed) == 1
    assert report.failed == ()
    # canonical assignment.json must survive retry intact
    assert json.loads((staging / "assignment.json").read_text()) == canonical


def test_retry_bounces_after_max_retries(tmp_path, monkeypatch):
    manifest = parse_worker_manifest(_MANIFEST)
    note = tmp_path / "inbox" / "g" / "n1.md"
    note.parent.mkdir(parents=True)
    note.write_text("# n\n")
    staging = tmp_path / "workers" / "w0001"
    failed = (_setup_failed_note(staging, "n1"),)

    monkeypatch.setenv("FAKE_CLAUDE_MODE", "augment_bad")

    report = asyncio.run(retry_failed(
        failed=failed, manifest=manifest, adapter_prompt_text="",
        worker_assignment=WorkerAssignment(worker_id="w0001", group="g", notes=(note,)),
        run_dir=tmp_path, vault_slug="v",
        max_retries=2, timeout_seconds=30,
    ))
    assert report.passed == ()
    assert len(report.failed) == 1
    bounced = staging / "failed" / "n1"
    assert bounced.exists()
    assert (bounced / "error.json").exists()
    err = json.loads((bounced / "error.json").read_text())
    assert err["slug"] == "n1"
    assert err["errors"]


def test_retry_records_exit_code_and_stderr_when_claude_fails(tmp_path, monkeypatch, caplog):
    manifest = parse_worker_manifest(_MANIFEST)
    note = tmp_path / "inbox" / "g" / "n1.md"
    note.parent.mkdir(parents=True)
    note.write_text("# n\n")
    staging = tmp_path / "workers" / "w0001"
    failed = (_setup_failed_note(staging, "n1"),)

    monkeypatch.setenv("FAKE_CLAUDE_MODE", "fail")

    with caplog.at_level(logging.WARNING, logger="rufino.engine.process.batch.retry"):
        report = asyncio.run(retry_failed(
            failed=failed, manifest=manifest, adapter_prompt_text="",
            worker_assignment=WorkerAssignment(worker_id="w0001", group="g", notes=(note,)),
            run_dir=tmp_path, vault_slug="v",
            max_retries=2, timeout_seconds=30,
        ))
    assert report.passed == ()
    assert len(report.failed) == 1
    err = json.loads((staging / "failed" / "n1" / "error.json").read_text())
    assert err["last_exit_code"] == 42
    assert "simulated unexpected failure" in err["last_stderr_tail"]
    assert any("exit_code=42" in r.message for r in caplog.records)


def test_retry_marks_missing_source_path_with_reason(tmp_path, monkeypatch, caplog):
    manifest = parse_worker_manifest(_MANIFEST)
    staging = tmp_path / "workers" / "w0001"
    # No matching note in worker_assignment for slug "ghost"
    failed = (_setup_failed_note(staging, "ghost"),)
    real_note = tmp_path / "inbox" / "g" / "other.md"
    real_note.parent.mkdir(parents=True)
    real_note.write_text("# other\n")

    monkeypatch.setenv("FAKE_CLAUDE_MODE", "augment")

    with caplog.at_level(logging.ERROR, logger="rufino.engine.process.batch.retry"):
        report = asyncio.run(retry_failed(
            failed=failed, manifest=manifest, adapter_prompt_text="",
            worker_assignment=WorkerAssignment(
                worker_id="w0001", group="g", notes=(real_note,),
            ),
            run_dir=tmp_path, vault_slug="v",
            max_retries=2, timeout_seconds=30,
        ))
    assert len(report.failed) == 1
    err = json.loads((staging / "failed" / "ghost" / "error.json").read_text())
    assert err["reason"] == "missing-source-path"
    assert any("ghost" in r.message and r.levelname == "ERROR" for r in caplog.records)


def test_retry_preserves_multi_note_canonical_assignment(tmp_path, monkeypatch):
    """Worker had A+B assigned, only A failed validation. After retry, the
    canonical assignment.json must still list BOTH notes (the consolidator
    in T12 reads this file)."""
    manifest = parse_worker_manifest(_MANIFEST)
    nA = tmp_path / "inbox" / "g" / "nA.md"
    nB = tmp_path / "inbox" / "g" / "nB.md"
    nA.parent.mkdir(parents=True)
    nA.write_text("# A\n")
    nB.write_text("# B\n")
    staging = tmp_path / "workers" / "w0001"
    failed = (_setup_failed_note(staging, "nA"),)
    canonical = _write_canonical_assignment(
        staging, run_id=tmp_path.name, worker_id="w0001", group="g", notes=(nA, nB),
    )

    monkeypatch.setenv("FAKE_CLAUDE_MODE", "augment")

    asyncio.run(retry_failed(
        failed=failed, manifest=manifest, adapter_prompt_text="",
        worker_assignment=WorkerAssignment(
            worker_id="w0001", group="g", notes=(nA, nB),
        ),
        run_dir=tmp_path, vault_slug="v",
        max_retries=2, timeout_seconds=30,
    ))
    final = json.loads((staging / "assignment.json").read_text())
    assert final == canonical
    assert len(final["notes"]) == 2
