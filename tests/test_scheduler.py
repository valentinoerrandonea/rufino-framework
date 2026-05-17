import pytest
from rufino.runtime.scheduler import (
    Scheduler,
    LaunchdScheduler,
    CronScheduler,
    ScheduledJob,
    pick_scheduler_for_os,
)


def test_scheduled_job_required_fields():
    job = ScheduledJob(name="rufino.test", cron="0 22 * * *", command="echo hi")
    assert job.name == "rufino.test"
    assert job.cron == "0 22 * * *"
    assert job.command == "echo hi"


def test_launchd_renders_plist():
    job = ScheduledJob(name="rufino.test", cron="0 22 * * *", command="/bin/echo hi")
    plist = LaunchdScheduler().render(job)
    assert "<key>Label</key>" in plist
    assert "<string>rufino.test</string>" in plist
    assert "<key>StartCalendarInterval</key>" in plist
    assert "<key>Hour</key>" in plist
    assert "<integer>22</integer>" in plist
    assert "<key>Minute</key>" in plist
    assert "<integer>0</integer>" in plist


def test_cron_renders_crontab_line():
    job = ScheduledJob(name="rufino.test", cron="0 22 * * *", command="/bin/echo hi")
    line = CronScheduler().render(job)
    assert line.strip() == "0 22 * * * /bin/echo hi # rufino-job:rufino.test"


def test_pick_scheduler_for_os_darwin():
    assert isinstance(pick_scheduler_for_os("Darwin"), LaunchdScheduler)


def test_pick_scheduler_for_os_linux():
    assert isinstance(pick_scheduler_for_os("Linux"), CronScheduler)


def test_pick_scheduler_for_os_unknown_raises():
    with pytest.raises(NotImplementedError):
        pick_scheduler_for_os("Windows")
