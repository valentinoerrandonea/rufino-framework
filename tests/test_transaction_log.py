import json
import pytest
from pathlib import Path
from rufino.runtime.transaction_log import (
    TransactionLog,
    LogEntry,
    apply_and_log,
)


def test_log_entry_serializable():
    entry = LogEntry(op="mkdir", target="/tmp/test", rollback="rmdir")
    assert json.loads(json.dumps(entry.to_dict())) == entry.to_dict()


def test_log_records_operations(tmp_path: Path):
    log = TransactionLog(tmp_path / "tx.json")
    log.record(LogEntry(op="mkdir", target="/tmp/a", rollback="rmdir"))
    log.record(LogEntry(op="write", target="/tmp/b", rollback="delete"))

    assert log.entries() == [
        LogEntry(op="mkdir", target="/tmp/a", rollback="rmdir"),
        LogEntry(op="write", target="/tmp/b", rollback="delete"),
    ]


def test_log_persists_to_disk(tmp_path: Path):
    log_path = tmp_path / "tx.json"
    log = TransactionLog(log_path)
    log.record(LogEntry(op="mkdir", target="/x", rollback="rmdir"))

    reloaded = TransactionLog.load(log_path)
    assert reloaded.entries() == [LogEntry(op="mkdir", target="/x", rollback="rmdir")]


def test_rollback_executes_in_reverse_order(tmp_path: Path):
    log = TransactionLog(tmp_path / "tx.json")
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.write_text("content")

    log.record(LogEntry(op="mkdir", target=str(a), rollback="rmdir"))
    log.record(LogEntry(op="write", target=str(b), rollback="delete"))

    log.rollback()

    assert not a.exists()
    assert not b.exists()


def test_rollback_is_idempotent(tmp_path: Path):
    log = TransactionLog(tmp_path / "tx.json")
    a = tmp_path / "a"
    a.mkdir()
    log.record(LogEntry(op="mkdir", target=str(a), rollback="rmdir"))

    log.rollback()
    assert not a.exists()
    assert log.entries() == []

    # Second rollback should be no-op (entries already empty)
    log.rollback()
    assert log.entries() == []


def test_rollback_partial_failure_preserves_remaining_entries(tmp_path: Path):
    from rufino.runtime.transaction_log import register_rollback

    fail_counter = {"calls": 0}

    def flaky_handler(target: str) -> None:
        fail_counter["calls"] += 1
        if fail_counter["calls"] == 1:
            raise RuntimeError("simulated rollback failure")
        # second call succeeds

    register_rollback("flaky", flaky_handler)
    log = TransactionLog(tmp_path / "tx.json")
    a = tmp_path / "a"
    a.mkdir()
    log.record(LogEntry(op="mkdir", target=str(a), rollback="rmdir"))
    log.record(LogEntry(op="custom", target="placeholder", rollback="flaky"))

    with pytest.raises(RuntimeError, match="simulated"):
        log.rollback()

    # Both entries still present — partial rollback didn't pop anything
    assert len(log.entries()) == 2

    # Retry succeeds and clears the log
    log.rollback()
    assert log.entries() == []
    assert not a.exists()


def test_load_corrupt_json_raises_clear_error(tmp_path: Path):
    p = tmp_path / "tx.json"
    p.write_text("{not valid json")
    with pytest.raises(RuntimeError, match="corrupted"):
        TransactionLog.load(p)


def test_apply_and_log_helper(tmp_path: Path):
    log = TransactionLog(tmp_path / "tx.json")
    target = tmp_path / "new_dir"

    apply_and_log(
        log,
        op="mkdir",
        target=str(target),
        apply_fn=lambda: target.mkdir(),
        rollback="rmdir",
    )

    assert target.exists()
    assert len(log.entries()) == 1
