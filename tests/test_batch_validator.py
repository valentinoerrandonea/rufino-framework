import json
from pathlib import Path

import pytest

from rufino.engine.process.batch.validator import (
    NoteValidation,
    ValidationReport,
    validate_worker_output,
)
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
  - extiende
tag_axes:
  - axis: materia
    format: "materia/{slug}"
destination_path: "x/{slug}.md"
"""


def _write_worker_output(staging, slug, frontmatter, delta):
    aug = staging / "augmented"
    deltas = staging / "deltas"
    aug.mkdir(parents=True, exist_ok=True)
    deltas.mkdir(parents=True, exist_ok=True)
    (aug / f"{slug}.md").write_text(frontmatter + "\n# body\n")
    if delta is not None:
        (deltas / f"{slug}.json").write_text(json.dumps(delta))


def test_valid_output_passes(tmp_path):
    manifest = parse_worker_manifest(_MANIFEST)
    fm = (
        "---\n"
        "title: ok\n"
        "materia: math\n"
        "tags: [materia/math]\n"
        "triples:\n"
        "  - {s: \"a\", r: \"tema-de\", o: \"b\"}\n"
        "---"
    )
    _write_worker_output(tmp_path, "good", fm, {
        "note_slug": "good", "tags_added": [], "triples_emitted": [],
        "concepts_referenced": [], "concepts_promoted": [],
        "wikilinks_added": [], "qa_opened": [], "warnings": [],
    })
    report = validate_worker_output(tmp_path, manifest)
    assert isinstance(report, ValidationReport)
    assert len(report.passed) == 1
    assert report.passed[0].slug == "good"
    assert report.failed == ()


def test_missing_required_field_flags(tmp_path):
    manifest = parse_worker_manifest(_MANIFEST)
    fm = "---\nmateria: math\n---"
    _write_worker_output(tmp_path, "bad", fm, {"note_slug": "bad"})
    report = validate_worker_output(tmp_path, manifest)
    assert len(report.failed) == 1
    assert any("title" in e for e in report.failed[0].errors)


def test_out_of_vocab_triple_flags(tmp_path):
    manifest = parse_worker_manifest(_MANIFEST)
    fm = (
        "---\n"
        "title: x\n"
        "materia: math\n"
        "triples:\n"
        "  - {s: \"a\", r: \"INVALID\", o: \"b\"}\n"
        "---"
    )
    _write_worker_output(tmp_path, "bad", fm, {"note_slug": "bad"})
    report = validate_worker_output(tmp_path, manifest)
    assert len(report.failed) == 1
    assert any("INVALID" in e for e in report.failed[0].errors)


def test_missing_delta_flags(tmp_path):
    manifest = parse_worker_manifest(_MANIFEST)
    fm = "---\ntitle: ok\nmateria: math\n---"
    _write_worker_output(tmp_path, "nodelta", fm, delta=None)
    report = validate_worker_output(tmp_path, manifest)
    assert len(report.failed) == 1
    assert any("delta" in e.lower() for e in report.failed[0].errors)


def test_malformed_delta_flags(tmp_path):
    manifest = parse_worker_manifest(_MANIFEST)
    aug = tmp_path / "augmented"
    deltas = tmp_path / "deltas"
    aug.mkdir(parents=True)
    deltas.mkdir(parents=True)
    (aug / "x.md").write_text("---\ntitle: t\nmateria: m\n---\n")
    (deltas / "x.json").write_text("{not: json}")
    report = validate_worker_output(tmp_path, manifest)
    assert len(report.failed) == 1
    assert any("json" in e.lower() for e in report.failed[0].errors)


def test_pending_only_is_skipped(tmp_path):
    manifest = parse_worker_manifest(_MANIFEST)
    pending = tmp_path / "pending"
    pending.mkdir()
    (pending / "x.json").write_text("{}")
    report = validate_worker_output(tmp_path, manifest)
    assert report.passed == ()
    assert report.failed == ()
