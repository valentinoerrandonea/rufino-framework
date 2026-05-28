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


def test_runner_skips_compression_check_when_floor_is_none(
    tmp_path, monkeypatch, batch_adapter, caplog,
):
    """No compression_floor in the manifest → no warning records ever."""
    import logging as _logging

    monkeypatch.setenv("FAKE_CLAUDE_MODE", "augment")
    vault, adapter, source = _make_minimal_setup(tmp_path, batch_adapter)

    with caplog.at_level(
        _logging.WARNING, logger="rufino.engine.process.batch.validator",
    ):
        result = asyncio.run(run_batch(
            source=source, adapter_dir=adapter, vault_root=vault,
            workers=1, batch_size=1, dry_run=False,
            skip_consolidator=True, timeout_seconds=10.0,
        ))

    assert result.compression_floor is None
    assert result.notes_below_compression_floor == 0
    assert not any(
        "compression below floor" in r.getMessage() for r in caplog.records
    )


def test_runner_emits_compression_warning_and_counts_when_below_floor(
    tmp_path, monkeypatch, batch_adapter, caplog,
):
    """Augmented body smaller than the floor must produce a warning record
    and bump notes_below_compression_floor in BatchRunResult."""
    import logging as _logging

    monkeypatch.setenv("FAKE_CLAUDE_MODE", "augment")
    adapter = batch_adapter(batch_size=1, compression_floor=0.9)
    source = tmp_path / "corpus"
    source.mkdir()
    (source / "n1.md").write_text(
        "# big input\n" + ("word " * 200), encoding="utf-8",
    )
    vault = tmp_path / "vault"

    with caplog.at_level(
        _logging.WARNING, logger="rufino.engine.process.batch.validator",
    ):
        result = asyncio.run(run_batch(
            source=source, adapter_dir=adapter, vault_root=vault,
            workers=1, batch_size=1, dry_run=False,
            skip_consolidator=True, timeout_seconds=10.0,
        ))

    assert result.compression_floor == 0.9
    assert result.notes_below_compression_floor >= 1
    matching = [
        r for r in caplog.records
        if "compression below floor" in r.getMessage()
    ]
    assert matching, "expected at least one compression warning record"
    # Tighter assertion: the warning identifies the note + floor, not just
    # a generic "below floor" string. Protects against regressions that
    # drop the actionable diagnostic.
    msg = matching[0].getMessage()
    assert "n1.md" in msg, f"warning should name the note, got: {msg}"
    assert "floor=0.90" in msg, f"warning should print floor=, got: {msg}"


def test_runner_persists_skipped_paths_in_run_json(
    tmp_path, monkeypatch, batch_adapter,
):
    """Per SF-2: the count alone is useless for diagnosing which docs failed.
    The full skipped paths must round-trip through run.json so users (and
    launchd-scheduled callers) can recover them post-hoc."""
    import json as _json

    monkeypatch.setenv("FAKE_CLAUDE_MODE", "augment")
    adapter = batch_adapter(batch_size=1)
    source = tmp_path / "corpus"
    (source / "materia1").mkdir(parents=True)
    (source / "materia1" / "ok.md").write_text("# ok\n")
    (source / "materia1" / "bad.xyz").write_text("?")  # unsupported → skipped
    vault = tmp_path / "vault"

    result = asyncio.run(run_batch(
        source=source, adapter_dir=adapter, vault_root=vault,
        workers=1, batch_size=1, dry_run=False,
        skip_consolidator=True, timeout_seconds=10.0,
    ))

    assert result.notes_skipped_stage == 1
    assert any("bad.xyz" in p for p in result.notes_skipped_stage_paths)
    run_dir = vault / ".rufino" / "runs" / result.run_id
    persisted = _json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert persisted["notes_skipped_stage"] == 1
    assert any("bad.xyz" in p for p in persisted["notes_skipped_stage_paths"])


def test_runner_naive_fallback_produces_typed_plan_and_commits(
    tmp_path, monkeypatch, batch_adapter,
):
    """Per TA-8: the naive-fallback branch builds typed Move/TagIndexUpdate
    objects now. Verify the end-to-end commit succeeds and the resulting
    vault state reflects the moves AND tag index updates."""
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "augment")
    vault, adapter, source = _make_minimal_setup(tmp_path, batch_adapter)

    result = asyncio.run(run_batch(
        source=source, adapter_dir=adapter, vault_root=vault,
        workers=1, batch_size=1, dry_run=False,
        skip_consolidator=True, timeout_seconds=10.0,
    ))

    assert result.notes_ok >= 1
    landed = [p for p in vault.rglob("n1.md") if ".rufino" not in str(p)]
    assert landed
    log_text = (vault / "_meta" / "_processing-log.md").read_text()
    assert "batch-naive-commit" in log_text


def test_build_worker_slug_index_disambiguates_same_stem_across_workers():
    """Per SF-1: the old slug-only index silently shadowed a same-stem note
    in a different group/worker, making the compression check compare the
    augmented output against the wrong original. The (worker_id, slug)
    index must keep both entries."""
    from pathlib import Path as _Path
    from rufino.engine.process.batch.planner import Plan, WorkerAssignment
    from rufino.engine.process.batch.runner import (
        _build_worker_slug_index, _worker_id_of,
    )

    plan = Plan(
        run_id="r1",
        adapter_dir="/x",
        workers=(
            WorkerAssignment(
                worker_id="w0001", group="tema1",
                notes=(_Path("/run/inbox/tema1/intro.md"),),
            ),
            WorkerAssignment(
                worker_id="w0002", group="tema2",
                notes=(_Path("/run/inbox/tema2/intro.md"),),
            ),
        ),
    )
    index = _build_worker_slug_index(plan)
    assert index[("w0001", "intro")] == _Path("/run/inbox/tema1/intro.md")
    assert index[("w0002", "intro")] == _Path("/run/inbox/tema2/intro.md")

    # _worker_id_of must recover the worker from a NoteValidation-shaped path.
    aug = _Path("/run/workers/w0001/augmented/intro.md")
    assert _worker_id_of(aug) == "w0001"
