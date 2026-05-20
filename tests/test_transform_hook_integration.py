"""Integration tests for Task 4.2 — transform_hook wired into Ingest + Process.

Covers the helper ``_maybe_apply_transform_hook`` and its two integration
sites:

* Ingest ``_run_emit_fact`` / ``_run_import_raw`` — hook runs between fetch
  and write.
* Process — hook runs between VALIDATE and CONSOLIDATE, mutating the
  augmented .md's frontmatter in place.

Graceful degrade is the load-bearing contract: a misbehaving hook surfaces
as a warning log, never an abort.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import yaml

from rufino.engine._transform_hook_invoker import _maybe_apply_transform_hook
from rufino.engine.ingest.runner import run_ingest
from rufino.engine.process.batch.runner import _apply_process_transform_hooks
from rufino.engine.process.batch.validator import NoteValidation
from rufino.engine.process.manifest import parse_worker_manifest


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------


def _write_hook(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def test_helper_returns_record_unchanged_when_hook_none(tmp_path: Path) -> None:
    record = {"a": 1}
    out = _maybe_apply_transform_hook(None, record, adapter_dir=tmp_path)
    assert out == record


def test_helper_returns_record_when_script_missing(
    tmp_path: Path, caplog
) -> None:
    record = {"a": 1}
    with caplog.at_level(logging.WARNING):
        out = _maybe_apply_transform_hook(
            Path("./does_not_exist.py"), record, adapter_dir=tmp_path,
        )
    assert out == record
    assert any("does not exist" in r.message for r in caplog.records)


def test_helper_applies_hook_when_present(tmp_path: Path) -> None:
    _write_hook(
        tmp_path / "transform.py",
        "import json, sys\n"
        "d = json.loads(sys.stdin.read())\n"
        "d['added'] = 'yes'\n"
        "sys.stdout.write(json.dumps(d))\n",
    )
    out = _maybe_apply_transform_hook(
        Path("./transform.py"), {"a": 1}, adapter_dir=tmp_path,
    )
    assert out == {"a": 1, "added": "yes"}


def test_helper_graceful_degrade_on_hook_error(
    tmp_path: Path, caplog
) -> None:
    _write_hook(
        tmp_path / "transform.py",
        "import sys\nsys.exit(1)\n",
    )
    record = {"a": 1}
    with caplog.at_level(logging.WARNING):
        out = _maybe_apply_transform_hook(
            Path("./transform.py"), record, adapter_dir=tmp_path,
        )
    assert out == record
    assert any("graceful degrade" in r.message for r in caplog.records)


def test_helper_rejects_path_escaping_adapter_dir(
    tmp_path: Path, caplog
) -> None:
    """Absolute hook paths (or `../` escapes) must not execute.

    Even if the file exists on disk, the helper has to refuse it to avoid
    arbitrary-code execution from a malicious adapter manifest.
    """
    adapter_dir = tmp_path / "adapter"
    adapter_dir.mkdir()
    evil = tmp_path / "evil.py"
    _write_hook(
        evil,
        "import json, sys\n"
        "d = json.loads(sys.stdin.read())\n"
        "d['pwned'] = True\n"
        "sys.stdout.write(json.dumps(d))\n",
    )
    record = {"a": 1}
    with caplog.at_level(logging.WARNING):
        out = _maybe_apply_transform_hook(
            evil, record, adapter_dir=adapter_dir,
        )
    assert out == record
    assert "pwned" not in out
    assert any("escapes adapter_dir" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Ingest emit_fact integration
# ---------------------------------------------------------------------------


_EMIT_FACT_MANIFEST = (
    "adapter_name: hooked\n"
    "source_name: hooked\n"
    "schedule: '*/30 * * * *'\n"
    "auth: {}\n"
    "output_mode: emit_fact\n"
    "emits: [t]\n"
    "fact_schema:\n  id: string\n"
    "destination:\n  facts: hooked/<id>.md\n"
    "dedup_by: id\n"
    "transform_hook: ./transform.py\n"
)

_EMIT_FACT_FETCHER = (
    "def fetch(since):\n"
    "    return [{'id': 'f1'}]\n"
)


def _build_emit_fact_adapter(
    adapter_dir: Path, hook_body: str | None = None,
) -> Path:
    adapter_dir.mkdir(parents=True, exist_ok=True)
    (adapter_dir / "manifest.yaml").write_text(_EMIT_FACT_MANIFEST)
    (adapter_dir / "fetcher.py").write_text(_EMIT_FACT_FETCHER)
    if hook_body is not None:
        (adapter_dir / "transform.py").write_text(hook_body)
    return adapter_dir


def test_emit_fact_hook_mutation_lands_in_frontmatter(
    tmp_vault: Path, tmp_path: Path
) -> None:
    adapter = _build_emit_fact_adapter(
        tmp_path / "adapter",
        hook_body=(
            "import json, sys\n"
            "d = json.loads(sys.stdin.read())\n"
            "d['enriched'] = 'hook-saw-this'\n"
            "sys.stdout.write(json.dumps(d))\n"
        ),
    )
    result = run_ingest(
        adapter_dir=adapter,
        vault_root=tmp_vault,
        rufino_state_dir=tmp_path / ".rufino-state",
    )
    assert result.facts_emitted == 1, result.errors

    fact_file = tmp_vault / "hooked" / "f1.md"
    assert fact_file.exists()
    text = fact_file.read_text(encoding="utf-8")
    # Body has only YAML frontmatter, so parse the block between '---' lines.
    _, fm_yaml, _ = text.split("---\n", 2)
    fm = yaml.safe_load(fm_yaml)
    assert fm["enriched"] == "hook-saw-this"


def test_emit_fact_hook_failure_falls_back_to_original_fact(
    tmp_vault: Path, tmp_path: Path, caplog
) -> None:
    adapter = _build_emit_fact_adapter(
        tmp_path / "adapter",
        hook_body=(
            "import sys\n"
            "sys.stderr.write('boom\\n')\n"
            "sys.exit(2)\n"
        ),
    )
    with caplog.at_level(logging.WARNING):
        result = run_ingest(
            adapter_dir=adapter,
            vault_root=tmp_vault,
            rufino_state_dir=tmp_path / ".rufino-state",
        )
    assert result.facts_emitted == 1, result.errors
    fact_file = tmp_vault / "hooked" / "f1.md"
    assert fact_file.exists()
    text = fact_file.read_text(encoding="utf-8")
    _, fm_yaml, _ = text.split("---\n", 2)
    fm = yaml.safe_load(fm_yaml)
    # No "enriched" key — the original fact landed.
    assert "enriched" not in fm
    assert fm["id"] == "f1"
    assert any("graceful degrade" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Ingest import_raw integration
# ---------------------------------------------------------------------------


_IMPORT_RAW_MANIFEST = (
    "adapter_name: raw-hooked\n"
    "source_name: raw-hooked\n"
    "schedule: '*/30 * * * *'\n"
    "auth: {}\n"
    "output_mode: import_raw\n"
    "target_inbox: inbox/\n"
    "process_with: x\n"
    "trigger: defer\n"
    "transform_hook: ./transform.py\n"
)

_IMPORT_RAW_FETCHER = (
    "def fetch(since):\n"
    "    return [{'filename': 'note.md', 'content': 'hello world'}]\n"
)


def test_import_raw_hook_mutates_content(
    tmp_vault: Path, tmp_path: Path,
) -> None:
    adapter = tmp_path / "raw-adapter"
    adapter.mkdir()
    (adapter / "manifest.yaml").write_text(_IMPORT_RAW_MANIFEST)
    (adapter / "fetcher.py").write_text(_IMPORT_RAW_FETCHER)
    (adapter / "transform.py").write_text(
        "import json, sys\n"
        "d = json.loads(sys.stdin.read())\n"
        "d['content'] = d['content'].upper()\n"
        "sys.stdout.write(json.dumps(d))\n"
    )

    run_ingest(
        adapter_dir=adapter,
        vault_root=tmp_vault,
        rufino_state_dir=tmp_path / ".rufino-state",
    )

    note = tmp_vault / "inbox" / "note.md"
    assert note.exists()
    assert note.read_text(encoding="utf-8") == "HELLO WORLD"


def test_import_raw_hook_failure_writes_original_content(
    tmp_vault: Path, tmp_path: Path, caplog,
) -> None:
    adapter = tmp_path / "raw-adapter-broken"
    adapter.mkdir()
    (adapter / "manifest.yaml").write_text(_IMPORT_RAW_MANIFEST)
    (adapter / "fetcher.py").write_text(_IMPORT_RAW_FETCHER)
    (adapter / "transform.py").write_text(
        "import sys\nsys.exit(3)\n"
    )

    with caplog.at_level(logging.WARNING):
        run_ingest(
            adapter_dir=adapter,
            vault_root=tmp_vault,
            rufino_state_dir=tmp_path / ".rufino-state",
        )

    note = tmp_vault / "inbox" / "note.md"
    assert note.exists()
    assert note.read_text(encoding="utf-8") == "hello world"
    assert any("graceful degrade" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Process integration — exercising _apply_process_transform_hooks directly.
# ---------------------------------------------------------------------------


_PROCESS_MANIFEST_NO_HOOK = """
adapter_name: x
note_type: x
applies_when: {source_dir: inbox/, matches_pattern: ["*.md"]}
llm: sonnet
mode_default: full
output_schema:
  required:
    title: string
triple_vocabulary: [tema-de]
tag_axes:
  - {axis: materia, format: "materia/{slug}"}
destination_path: "x/{slug}.md"
"""


_PROCESS_MANIFEST_WITH_HOOK = _PROCESS_MANIFEST_NO_HOOK + "transform_hook: ./transform.py\n"


def _stage_augmented(run_dir: Path, slug: str, fm: dict, body: str = "# body\n") -> Path:
    aug_dir = run_dir / "workers" / "w001" / "augmented"
    aug_dir.mkdir(parents=True, exist_ok=True)
    fm_yaml = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True)
    path = aug_dir / f"{slug}.md"
    path.write_text(f"---\n{fm_yaml}---\n{body}", encoding="utf-8")
    return path


def test_process_hook_mutates_augmented_frontmatter(tmp_path: Path) -> None:
    adapter = tmp_path / "adapter"
    adapter.mkdir()
    (adapter / "transform.py").write_text(
        "import json, sys\n"
        "fm = json.loads(sys.stdin.read())\n"
        "fm['enriched_by_hook'] = True\n"
        "sys.stdout.write(json.dumps(fm))\n"
    )
    manifest = parse_worker_manifest(_PROCESS_MANIFEST_WITH_HOOK)

    run_dir = tmp_path / "run"
    aug_path = _stage_augmented(run_dir, "note-a", {"title": "Note A"})
    passed = (
        NoteValidation(
            slug="note-a", augmented_path=aug_path, delta_path=None,
        ),
    )

    _apply_process_transform_hooks(passed, manifest=manifest, adapter_dir=adapter)

    text = aug_path.read_text(encoding="utf-8")
    _, fm_yaml, body = text.split("---\n", 2)
    fm = yaml.safe_load(fm_yaml)
    assert fm["title"] == "Note A"
    assert fm["enriched_by_hook"] is True
    assert body.strip() == "# body"


def test_process_hook_failure_leaves_note_unchanged(
    tmp_path: Path, caplog,
) -> None:
    adapter = tmp_path / "adapter"
    adapter.mkdir()
    (adapter / "transform.py").write_text(
        "import sys\nsys.exit(4)\n"
    )
    manifest = parse_worker_manifest(_PROCESS_MANIFEST_WITH_HOOK)

    run_dir = tmp_path / "run"
    aug_path = _stage_augmented(run_dir, "note-b", {"title": "Note B"})
    original_text = aug_path.read_text(encoding="utf-8")
    passed = (
        NoteValidation(
            slug="note-b", augmented_path=aug_path, delta_path=None,
        ),
    )

    with caplog.at_level(logging.WARNING):
        _apply_process_transform_hooks(passed, manifest=manifest, adapter_dir=adapter)

    # Untouched.
    assert aug_path.read_text(encoding="utf-8") == original_text
    assert any("graceful degrade" in r.message for r in caplog.records)


def test_process_hook_skipped_when_manifest_field_unset(tmp_path: Path) -> None:
    adapter = tmp_path / "adapter"
    adapter.mkdir()
    manifest = parse_worker_manifest(_PROCESS_MANIFEST_NO_HOOK)

    run_dir = tmp_path / "run"
    aug_path = _stage_augmented(run_dir, "note-c", {"title": "Note C"})
    original = aug_path.read_text(encoding="utf-8")
    passed = (
        NoteValidation(
            slug="note-c", augmented_path=aug_path, delta_path=None,
        ),
    )

    _apply_process_transform_hooks(passed, manifest=manifest, adapter_dir=adapter)

    assert aug_path.read_text(encoding="utf-8") == original


def test_process_hook_skips_note_without_frontmatter(tmp_path: Path) -> None:
    """Defensive guard: if a passed note has no FM, the hook must not run.

    Otherwise a hook returning ``{'k': 'v'}`` would unconditionally prepend a
    new frontmatter block — silently turning a no-FM note into a has-FM note.
    Validator should reject FM-less augmented files upstream; this is belt
    and suspenders.
    """
    adapter = tmp_path / "adapter"
    adapter.mkdir()
    (adapter / "transform.py").write_text(
        "import json, sys\n"
        "fm = json.loads(sys.stdin.read())\n"
        "fm['injected'] = True\n"
        "sys.stdout.write(json.dumps(fm))\n"
    )
    manifest = parse_worker_manifest(_PROCESS_MANIFEST_WITH_HOOK)

    run_dir = tmp_path / "run"
    aug_dir = run_dir / "workers" / "w001" / "augmented"
    aug_dir.mkdir(parents=True)
    aug_path = aug_dir / "no-fm.md"
    body = "# just a body, no frontmatter\n"
    aug_path.write_text(body, encoding="utf-8")
    passed = (
        NoteValidation(
            slug="no-fm", augmented_path=aug_path, delta_path=None,
        ),
    )

    _apply_process_transform_hooks(passed, manifest=manifest, adapter_dir=adapter)

    # File content unchanged — no FM block prepended.
    assert aug_path.read_text(encoding="utf-8") == body


def test_process_hook_does_not_abort_on_date_in_frontmatter(
    tmp_path: Path,
) -> None:
    """A frontmatter ``created: <date>`` value must not crash the hook batch.

    PyYAML deserializes bare ISO dates as ``datetime.date``. Before the
    ``json.dumps(default=str)`` hardening, this would raise ``TypeError``
    inside ``run_transform_hook`` — which is NOT caught by the
    (OSError, UnicodeDecodeError, FrontmatterError) guards around
    ``_apply_process_transform_hooks``, so the whole batch would abort.

    With the fix, the date is sent to the hook as the string "2026-05-19".
    After the hook (identity), the new frontmatter dict equals the old one
    (the original ``datetime.date`` value also compares equal to that same
    date when YAML-reloaded), so the file is left untouched. Either way:
    no exception escapes.
    """
    from datetime import date

    adapter = tmp_path / "adapter"
    adapter.mkdir()
    # Identity hook — read JSON, echo it back unchanged.
    (adapter / "transform.py").write_text(
        "import json, sys\n"
        "fm = json.loads(sys.stdin.read())\n"
        "sys.stdout.write(json.dumps(fm))\n"
    )
    manifest = parse_worker_manifest(_PROCESS_MANIFEST_WITH_HOOK)

    run_dir = tmp_path / "run"
    aug_path = _stage_augmented(
        run_dir, "dated", {"title": "Dated", "created": date(2026, 5, 19)},
    )
    passed = (
        NoteValidation(slug="dated", augmented_path=aug_path, delta_path=None),
    )

    # MUST NOT RAISE. Before the fix, this raised TypeError.
    _apply_process_transform_hooks(
        passed, manifest=manifest, adapter_dir=adapter,
    )

    # Frontmatter still parses cleanly and still has both keys.
    text = aug_path.read_text(encoding="utf-8")
    _, fm_yaml, _ = text.split("---\n", 2)
    fm = yaml.safe_load(fm_yaml)
    assert fm["title"] == "Dated"
    # `created` may now be either a date (file untouched because the
    # date→str-coerced dict still compared equal to the original via PyYAML
    # round-trip) or the literal string "2026-05-19" (file rewritten). Both
    # outcomes prove the TypeError no longer escapes; that's what we care
    # about. Assert on the value either way.
    assert str(fm["created"]) == "2026-05-19"


def test_process_hook_continues_after_one_note_fails(tmp_path: Path) -> None:
    """If the hook fails on note-a, note-b must still get mutated.

    Implementation must be per-note try/except, not a single try block.
    """
    adapter = tmp_path / "adapter"
    adapter.mkdir()
    # Hook fails when the input frontmatter title is "fail", succeeds otherwise.
    (adapter / "transform.py").write_text(
        "import json, sys\n"
        "fm = json.loads(sys.stdin.read())\n"
        "if fm.get('title') == 'fail':\n"
        "    sys.exit(1)\n"
        "fm['ok'] = True\n"
        "sys.stdout.write(json.dumps(fm))\n"
    )
    manifest = parse_worker_manifest(_PROCESS_MANIFEST_WITH_HOOK)

    run_dir = tmp_path / "run"
    aug_a = _stage_augmented(run_dir, "a", {"title": "fail"})
    aug_b = _stage_augmented(run_dir, "b", {"title": "ok"})
    original_a = aug_a.read_text(encoding="utf-8")
    passed = (
        NoteValidation(slug="a", augmented_path=aug_a, delta_path=None),
        NoteValidation(slug="b", augmented_path=aug_b, delta_path=None),
    )

    _apply_process_transform_hooks(passed, manifest=manifest, adapter_dir=adapter)

    assert aug_a.read_text(encoding="utf-8") == original_a, "note-a should be unchanged"
    _, fm_yaml_b, _ = aug_b.read_text(encoding="utf-8").split("---\n", 2)
    fm_b = yaml.safe_load(fm_yaml_b)
    assert fm_b["ok"] is True, "note-b should have been mutated by hook"
