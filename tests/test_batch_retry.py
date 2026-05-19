import asyncio
import json
import os
from pathlib import Path

import pytest

from rufino.engine.process.batch.planner import WorkerAssignment
from rufino.engine.process.batch.retry import retry_failed
from rufino.engine.process.batch.validator import NoteValidation, ValidationReport
from rufino.engine.process.manifest import parse_worker_manifest


FAKE_DIR = Path("tests/fixtures/fake_claude").resolve()


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
def _fake_claude_on_path(monkeypatch):
    monkeypatch.setenv("PATH", str(FAKE_DIR) + os.pathsep + os.environ["PATH"])


def _setup_failed_note(staging: Path, slug: str) -> NoteValidation:
    aug = staging / "augmented" / f"{slug}.md"
    aug.parent.mkdir(parents=True, exist_ok=True)
    aug.write_text("---\nmateria: x\n---\n# body\n")
    return NoteValidation(
        slug=slug, augmented_path=aug, delta_path=None,
        errors=("schema violation: missing 'title'",),
    )


def test_retry_succeeds_on_second_try(tmp_path, monkeypatch):
    manifest = parse_worker_manifest(_MANIFEST)
    note = tmp_path / "inbox" / "g" / "n1.md"
    note.parent.mkdir(parents=True)
    note.write_text("# n\n")
    staging = tmp_path / "workers" / "w001"
    failed = (_setup_failed_note(staging, "n1"),)

    monkeypatch.setenv("FAKE_CLAUDE_MODE", "augment")

    report = asyncio.run(retry_failed(
        failed=failed, manifest=manifest, adapter_prompt_text="",
        worker_assignment=WorkerAssignment(worker_id="w001", group="g", notes=(note,)),
        run_dir=tmp_path, vault_slug="v",
        max_retries=2, timeout_seconds=30,
    ))
    assert len(report.passed) == 1
    assert report.failed == ()


def test_retry_bounces_after_max_retries(tmp_path, monkeypatch):
    manifest = parse_worker_manifest(_MANIFEST)
    note = tmp_path / "inbox" / "g" / "n1.md"
    note.parent.mkdir(parents=True)
    note.write_text("# n\n")
    staging = tmp_path / "workers" / "w001"
    failed = (_setup_failed_note(staging, "n1"),)

    monkeypatch.setenv("FAKE_CLAUDE_MODE", "augment_bad")

    report = asyncio.run(retry_failed(
        failed=failed, manifest=manifest, adapter_prompt_text="",
        worker_assignment=WorkerAssignment(worker_id="w001", group="g", notes=(note,)),
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
