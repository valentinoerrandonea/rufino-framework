"""End-to-end tests for the process-batch top-level runner."""
import asyncio
from pathlib import Path

import pytest

from rufino.engine.process.batch.errors import BatchError
from rufino.engine.process.batch.runner import (
    BatchRunResult,
    run_batch,
)


@pytest.fixture(autouse=True)
def _fake_claude(fake_claude_on_path):
    """Autouse delegate to shared conftest fixture (FAKE_CLAUDE_DIR on PATH)."""
    yield


def _make_minimal_setup(
    tmp_path: Path, batch_adapter
) -> tuple[Path, Path, Path]:
    """Smallest viable batch input: a vault dir, an adapter, and a 1-note corpus.

    Returns ``(vault, adapter, source)``.
    """
    vault = tmp_path / "vault"
    vault.mkdir()
    adapter = batch_adapter(batch_size=5)
    source = tmp_path / "corpus"
    source.mkdir()
    (source / "n1.md").write_text("# n1\n", encoding="utf-8")
    return vault, adapter, source


def test_dry_run_stops_after_plan(tmp_path, monkeypatch, batch_adapter):
    adapter = batch_adapter(batch_size=5)
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


def test_full_run_commits(tmp_path, monkeypatch, batch_adapter):
    adapter = batch_adapter(batch_size=5)
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


def test_empty_corpus_raises_batcherror(tmp_path, monkeypatch, batch_adapter):
    """Source dir with no recognizable notes should fail fast, not enter
    DISPATCH with an empty plan."""
    adapter = batch_adapter(batch_size=5)
    source = tmp_path / "empty_corpus"
    source.mkdir()
    vault = tmp_path / "vault"

    monkeypatch.setenv("FAKE_CLAUDE_MODE", "augment")
    with pytest.raises(BatchError, match="empty"):
        asyncio.run(run_batch(
            source=source, adapter_dir=adapter, vault_root=vault,
            workers=None, batch_size=None, dry_run=False,
        ))


def test_consolidator_returns_none_falls_back_to_naive(
    tmp_path, monkeypatch, batch_adapter
):
    """With ``skip_consolidator=False``, run_consolidator is invoked. The
    fake_claude binary in ``augment`` mode does NOT write
    ``consolidation-plan.json``, so the consolidator returns None and the
    naive fallback must take over and commit the note."""
    adapter = batch_adapter(batch_size=5)
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


def test_validate_failure_triggers_retry(tmp_path, monkeypatch, batch_adapter):
    """``augment_bad`` makes the worker emit invalid frontmatter. Validation
    fails, retry fires (and also fails with augment_bad), the note ends up in
    ``notes_failed`` and a failed/ marker is on disk."""
    adapter = batch_adapter(batch_size=5)
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
    failed_marker = run_dir / "workers" / "w0001" / "failed" / "n1" / "error.json"
    assert failed_marker.exists(), (
        "retry should have bounced the note to failed/ after exhausting attempts"
    )


def test_pending_qa_written_to_vault(tmp_path, monkeypatch, batch_adapter):
    """``qa`` mode makes the worker emit a pending question. The runner
    collects it and writes a question file into the vault."""
    adapter = batch_adapter(batch_size=5)
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


def test_runner_empty_worker_output_counts_as_failure(
    tmp_path, monkeypatch, batch_adapter
):
    """Codex C2: FAKE_CLAUDE_MODE=empty must produce notes_failed == notes_total."""
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "empty")
    vault, adapter, source = _make_minimal_setup(tmp_path, batch_adapter)

    result = asyncio.run(run_batch(
        source=source, adapter_dir=adapter, vault_root=vault,
        workers=1, batch_size=1, dry_run=False,
        skip_consolidator=True, timeout_seconds=10.0,
    ))

    assert result.notes_total == 1
    assert result.notes_ok == 0
    assert result.notes_failed == 1


def test_runner_worker_timeout_counts_as_failure(
    tmp_path, monkeypatch, batch_adapter
):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "hang")
    vault, adapter, source = _make_minimal_setup(tmp_path, batch_adapter)

    result = asyncio.run(run_batch(
        source=source, adapter_dir=adapter, vault_root=vault,
        workers=1, batch_size=1, dry_run=False,
        skip_consolidator=True, timeout_seconds=0.5,
    ))

    assert result.notes_failed == 1
    assert result.notes_ok == 0


def test_runner_worker_nonzero_exit_counts_as_failure(
    tmp_path, monkeypatch, batch_adapter
):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "fail")
    vault, adapter, source = _make_minimal_setup(tmp_path, batch_adapter)

    result = asyncio.run(run_batch(
        source=source, adapter_dir=adapter, vault_root=vault,
        workers=1, batch_size=1, dry_run=False,
        skip_consolidator=True, timeout_seconds=10.0,
    ))

    assert result.notes_failed == 1


def test_runner_uses_consolidator_plan_when_available(
    tmp_path, monkeypatch, batch_adapter
):
    """H10 claude: consolidator happy path must drive commit, not naive fallback.

    fake_claude in ``augment_then_consolidate`` mode acts as a worker when
    invoked with cwd containing an ``assignment.json`` and as the
    consolidator when invoked from a cwd that has a ``workers/`` subdir
    (the run_dir). The latter writes a real ``consolidation-plan.json``
    with the marker log_entry ``"fake consolidator"``. We verify the
    consolidator path drove the commit by reading the vault's processing
    log — only the consolidator-produced plan injects that marker; the
    naive fallback would emit ``batch-naive-commit ...``.
    """
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "augment_then_consolidate")
    vault, adapter, source = _make_minimal_setup(tmp_path, batch_adapter)

    result = asyncio.run(run_batch(
        source=source, adapter_dir=adapter, vault_root=vault,
        workers=1, batch_size=1, dry_run=False,
        skip_consolidator=False, timeout_seconds=10.0,
    ))

    assert result.notes_ok >= 1
    run_dir = vault / ".rufino" / "runs" / result.run_id
    # Consolidator wrote its plan, naive fallback should not have run.
    assert (run_dir / "consolidation-plan.json").exists(), (
        "consolidator should have produced consolidation-plan.json"
    )
    # The plan's log_entries flow through commit -> _meta/_processing-log.md.
    processing_log = vault / "_meta" / "_processing-log.md"
    assert processing_log.exists(), "commit should have written the processing log"
    log_text = processing_log.read_text(encoding="utf-8")
    assert "fake consolidator" in log_text, (
        f"expected consolidator marker in processing log, got:\n{log_text}"
    )
    assert "batch-naive-commit" not in log_text, (
        "naive fallback should not have run when consolidator returned a plan"
    )
