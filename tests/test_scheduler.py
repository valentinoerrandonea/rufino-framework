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


def test_scheduled_job_rejects_newline_in_name():
    with pytest.raises(ValueError, match="newlines"):
        ScheduledJob(name="bad\nname", cron="0 0 * * *", command="echo")


def test_scheduled_job_rejects_newline_in_command():
    with pytest.raises(ValueError, match="newlines"):
        ScheduledJob(name="ok", cron="0 0 * * *", command="echo hi\nrm -rf /")


def test_scheduled_job_rejects_malformed_cron():
    with pytest.raises(ValueError, match="5 fields"):
        ScheduledJob(name="ok", cron="0 0 * *", command="echo")


def test_launchd_rejects_out_of_range_hour():
    job = ScheduledJob(name="ok", cron="0 25 * * *", command="echo")
    with pytest.raises(ValueError, match="out of range"):
        LaunchdScheduler().render(job)


def test_launchd_rejects_out_of_range_minute():
    job = ScheduledJob(name="ok", cron="60 0 * * *", command="echo")
    with pytest.raises(ValueError, match="out of range"):
        LaunchdScheduler().render(job)


def test_scheduler_escapes_xml_special_chars_in_command():
    import xml.etree.ElementTree as ET
    from rufino.runtime.scheduler import LaunchdScheduler, ScheduledJob
    job = ScheduledJob(
        name="com.example.test",
        command="echo 'a < b && c > d'",
        cron="0 22 * * *",
    )
    plist = LaunchdScheduler().render(job)
    root = ET.fromstring(plist)  # must parse cleanly
    assert root is not None
    assert "a < b && c > d" not in plist  # raw must not appear
    assert "a &lt; b &amp;&amp; c &gt; d" in plist


def test_scheduler_rejects_bad_name():
    import pytest
    from rufino.runtime.scheduler import ScheduledJob
    with pytest.raises(ValueError):
        ScheduledJob(name="../../etc/passwd", command="x", cron="0 22 * * *")
