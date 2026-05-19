import platform

import pytest

from rufino.runtime.scheduler import (
    ScheduledJob,
    get_backend,
    validate_cron,
)


def test_get_backend_returns_platform_appropriate_backend():
    system = platform.system()
    backend = get_backend()
    if system == "Darwin":
        from rufino.runtime.scheduler.launchd import LaunchdBackend
        assert isinstance(backend, LaunchdBackend)
    elif system == "Linux":
        from rufino.runtime.scheduler.cron import CronBackend
        assert isinstance(backend, CronBackend)
    else:
        pytest.skip(f"backend test only on Darwin/Linux, got {system}")


def test_validate_cron_accepts_all_stars():
    validate_cron("* * * * *")


def test_validate_cron_accepts_simple_values():
    validate_cron("0 22 * * *")
    validate_cron("30 14 1 6 0")


def test_validate_cron_accepts_step_syntax():
    validate_cron("*/15 * * * *")
    validate_cron("0 */6 * * *")


def test_validate_cron_rejects_wrong_field_count():
    with pytest.raises(ValueError, match="5 fields"):
        validate_cron("0 22 * *")
    with pytest.raises(ValueError, match="5 fields"):
        validate_cron("0 22 * * * *")


def test_validate_cron_rejects_out_of_range_minute():
    with pytest.raises(ValueError, match="out of range"):
        validate_cron("60 0 * * *")


def test_validate_cron_rejects_out_of_range_hour():
    with pytest.raises(ValueError, match="out of range"):
        validate_cron("0 24 * * *")


def test_validate_cron_rejects_non_numeric_field():
    with pytest.raises(ValueError, match="Invalid"):
        validate_cron("foo 0 * * *")


def test_validate_cron_rejects_bad_step():
    with pytest.raises(ValueError, match="step"):
        validate_cron("*/foo * * * *")


def test_scheduled_job_still_importable_from_package():
    job = ScheduledJob(name="rufino.test", cron="0 22 * * *", command="echo hi")
    assert job.name == "rufino.test"
