"""End-to-end smoke test of all foundation modules together."""
from pathlib import Path

from rufino import __version__
from rufino.helpers import v1
from rufino.runtime.scheduler import ScheduledJob, pick_scheduler_for_os, LaunchdScheduler
from rufino.runtime.secrets import InMemorySecretStore
from rufino.runtime.transaction_log import TransactionLog, LogEntry, apply_and_log
from rufino.runtime.validator_base import ValidationResult, ValidationError


def test_foundation_modules_compose(tmp_path: Path):
    # 1. Framework version + helper version reported
    assert __version__ == "0.0.1"
    assert v1.HELPER_VERSION == "1.0.0"

    # 2. Scheduler renders a job (use Darwin path; doesn't actually install)
    job = ScheduledJob(name="rufino.smoke", cron="0 22 * * *", command="/bin/true")
    plist = LaunchdScheduler().render(job)
    assert "rufino.smoke" in plist

    # 3. Secrets in-memory store roundtrips
    store = InMemorySecretStore()
    store.set("rufino-smoke", "user", "secret")
    assert store.get("rufino-smoke", "user") == "secret"

    # 4. Transaction log records + rolls back filesystem ops
    log_path = tmp_path / "tx.json"
    log = TransactionLog(log_path)
    target = tmp_path / "smoke_dir"
    apply_and_log(
        log,
        op="mkdir",
        target=str(target),
        apply_fn=lambda: target.mkdir(),
        rollback="rmdir",
    )
    assert target.exists()
    log.rollback()
    assert not target.exists()

    # 5. ValidationResult composes correctly
    result = ValidationResult(
        errors=[ValidationError(field="x", message="bad")],
        warnings=[],
    )
    assert result.ok is False
    assert "ERROR" in result.report()
