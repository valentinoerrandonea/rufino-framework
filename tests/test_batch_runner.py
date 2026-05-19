"""End-to-end tests for the process-batch top-level runner."""
import asyncio
import os
from pathlib import Path

import pytest

from rufino.engine.process.batch.errors import BatchError
from rufino.engine.process.batch.runner import (
    BatchRunResult,
    run_batch,
)


FAKE_DIR = Path(__file__).parent / "fixtures" / "fake_claude"


@pytest.fixture(autouse=True)
def _fake_claude(monkeypatch):
    monkeypatch.setenv("PATH", str(FAKE_DIR.resolve()) + os.pathsep + os.environ["PATH"])


def _make_adapter(tmp_path: Path) -> Path:
    adapter = tmp_path / "adapter"
    adapter.mkdir()
    (adapter / "manifest.yaml").write_text("""
adapter_name: x
note_type: x
applies_when: {source_dir: inbox/, matches_pattern: ["*.md"]}
llm: sonnet
mode_default: full
output_schema:
  required:
    title: string
    materia: string
triple_vocabulary: [tema-de]
tag_axes: [{axis: materia, format: "materia/{slug}"}]
destination_path: "apuntes/{slug}.md"
batch_size: 5
""")
    (adapter / "prompt.md").write_text("# instructions\n")
    return adapter


def test_dry_run_stops_after_plan(tmp_path, monkeypatch):
    adapter = _make_adapter(tmp_path)
    source = tmp_path / "corpus"
    (source / "math").mkdir(parents=True)
    (source / "math" / "n1.md").write_text("# n1\n")
    vault = tmp_path / "vault"

    monkeypatch.setenv("FAKE_CLAUDE_MODE", "augment")
    result = asyncio.run(run_batch(
        source=source, adapter_dir=adapter, vault_root=vault,
        workers=None, batch_size=None, dry_run=True,
    ))
    assert result.dry_run is True
    run_dir = vault / ".rufino" / "runs" / result.run_id
    assert (run_dir / "plan.json").exists()
    assert not (run_dir / "workers").exists()


def test_full_run_commits(tmp_path, monkeypatch):
    adapter = _make_adapter(tmp_path)
    source = tmp_path / "corpus"
    (source / "math").mkdir(parents=True)
    (source / "math" / "n1.md").write_text("# n1\n")
    vault = tmp_path / "vault"
    (vault / "_meta").mkdir(parents=True)
    (vault / "_meta" / "_tags.md").write_text("")

    monkeypatch.setenv("FAKE_CLAUDE_MODE", "augment")
    result = asyncio.run(run_batch(
        source=source, adapter_dir=adapter, vault_root=vault,
        workers=2, batch_size=None, dry_run=False,
        skip_consolidator=True,
    ))
    assert isinstance(result, BatchRunResult)
    assert result.notes_ok >= 1
    landed = [p for p in vault.rglob("n1.md") if ".rufino" not in str(p)]
    assert landed, "no committed note in vault canon"


def test_empty_corpus_raises_batcherror(tmp_path, monkeypatch):
    """Source dir with no recognizable notes should fail fast, not enter
    DISPATCH with an empty plan."""
    adapter = _make_adapter(tmp_path)
    source = tmp_path / "empty_corpus"
    source.mkdir()
    vault = tmp_path / "vault"

    monkeypatch.setenv("FAKE_CLAUDE_MODE", "augment")
    with pytest.raises(BatchError, match="empty"):
        asyncio.run(run_batch(
            source=source, adapter_dir=adapter, vault_root=vault,
            workers=None, batch_size=None, dry_run=False,
        ))


def test_consolidator_returns_none_falls_back_to_naive(tmp_path, monkeypatch):
    """With ``skip_consolidator=False``, run_consolidator is invoked. The
    fake_claude binary in ``augment`` mode does NOT write
    ``consolidation-plan.json``, so the consolidator returns None and the
    naive fallback must take over and commit the note."""
    adapter = _make_adapter(tmp_path)
    source = tmp_path / "corpus"
    (source / "math").mkdir(parents=True)
    (source / "math" / "n1.md").write_text("# n1\n")
    vault = tmp_path / "vault"

    monkeypatch.setenv("FAKE_CLAUDE_MODE", "augment")
    result = asyncio.run(run_batch(
        source=source, adapter_dir=adapter, vault_root=vault,
        workers=1, batch_size=None, dry_run=False,
        timeout_seconds=10.0,
    ))
    run_dir = vault / ".rufino" / "runs" / result.run_id
    assert not (run_dir / "consolidation-plan.json").exists(), (
        "fake_claude shouldn't have produced a consolidation plan"
    )
    landed = [p for p in vault.rglob("n1.md") if ".rufino" not in str(p)]
    assert landed, "naive fallback did not commit the note to vault canon"


def test_validate_failure_triggers_retry(tmp_path, monkeypatch):
    """``augment_bad`` makes the worker emit invalid frontmatter. Validation
    fails, retry fires (and also fails with augment_bad), the note ends up in
    ``notes_failed`` and a failed/ marker is on disk."""
    adapter = _make_adapter(tmp_path)
    source = tmp_path / "corpus"
    (source / "math").mkdir(parents=True)
    (source / "math" / "n1.md").write_text("# n1\n")
    vault = tmp_path / "vault"

    monkeypatch.setenv("FAKE_CLAUDE_MODE", "augment_bad")
    result = asyncio.run(run_batch(
        source=source, adapter_dir=adapter, vault_root=vault,
        workers=1, batch_size=None, dry_run=False,
        skip_consolidator=True,
    ))
    assert result.notes_failed >= 1, (
        "augment_bad output should have ended up counted as failed"
    )
    assert result.notes_ok == 0
    run_dir = vault / ".rufino" / "runs" / result.run_id
    failed_marker = run_dir / "workers" / "w001" / "failed" / "n1" / "error.json"
    assert failed_marker.exists(), (
        "retry should have bounced the note to failed/ after exhausting attempts"
    )


def test_pending_qa_written_to_vault(tmp_path, monkeypatch):
    """``qa`` mode makes the worker emit a pending question. The runner
    collects it and writes a question file into the vault."""
    adapter = _make_adapter(tmp_path)
    source = tmp_path / "corpus"
    (source / "math").mkdir(parents=True)
    (source / "math" / "n1.md").write_text("# n1\n")
    vault = tmp_path / "vault"

    monkeypatch.setenv("FAKE_CLAUDE_MODE", "qa")
    result = asyncio.run(run_batch(
        source=source, adapter_dir=adapter, vault_root=vault,
        workers=1, batch_size=None, dry_run=False,
        skip_consolidator=True,
    ))
    assert result.notes_pending_qa >= 1
    questions = list((vault / "questions").glob("*.md"))
    assert questions, "no question file written to vault/questions/"
