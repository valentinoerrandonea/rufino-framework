import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from rufino.runtime.scheduler.launchd import LaunchdBackend, _build_plist


class FakeRunner:
    def __init__(self, *, fail_bootstrap: bool = False, fail_bootout: bool = False):
        self.calls: list[list[str]] = []
        self._fail_bootstrap = fail_bootstrap
        self._fail_bootout = fail_bootout

    def __call__(self, cmd):
        cmd = list(cmd)
        self.calls.append(cmd)
        if cmd[:2] == ["launchctl", "bootstrap"] and self._fail_bootstrap:
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="boom")
        if cmd[:2] == ["launchctl", "bootout"] and self._fail_bootout:
            return subprocess.CompletedProcess(cmd, 36, stdout="", stderr="not loaded")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")


def test_install_writes_plist_and_calls_launchctl(tmp_path: Path) -> None:
    runner = FakeRunner()
    backend = LaunchdBackend(launchagents_dir=tmp_path, runner=runner)
    backend.install(
        job_id="rufino-ingest-facultad-drive",
        schedule="0 22 * * *",
        cmd="/usr/bin/env rufino ingest /tmp/adapter --vault /tmp/vault",
        log_path="/tmp/log.log",
    )
    plist = tmp_path / "rufino-ingest-facultad-drive.plist"
    assert plist.exists()
    assert "<key>Label</key>" in plist.read_text()
    assert any(c[:2] == ["launchctl", "bootstrap"] for c in runner.calls)
    assert any(c[:2] == ["launchctl", "bootout"] for c in runner.calls)


def test_install_idempotent_bootout_before_bootstrap(tmp_path: Path) -> None:
    runner = FakeRunner(fail_bootout=True)  # job not yet loaded — exit 36 ignored
    backend = LaunchdBackend(launchagents_dir=tmp_path, runner=runner)
    backend.install(
        job_id="rufino-ingest-x",
        schedule="0 22 * * *",
        cmd="echo hi",
        log_path="/tmp/x.log",
    )
    bootout_calls = [c for c in runner.calls if c[:2] == ["launchctl", "bootout"]]
    bootstrap_calls = [c for c in runner.calls if c[:2] == ["launchctl", "bootstrap"]]
    assert bootout_calls and bootstrap_calls
    assert runner.calls.index(bootout_calls[0]) < runner.calls.index(bootstrap_calls[0])


def test_install_raises_if_bootstrap_fails_and_removes_plist(tmp_path: Path) -> None:
    runner = FakeRunner(fail_bootstrap=True)
    backend = LaunchdBackend(launchagents_dir=tmp_path, runner=runner)
    with pytest.raises(RuntimeError, match="bootstrap"):
        backend.install(
            job_id="rufino-ingest-bad",
            schedule="0 22 * * *",
            cmd="echo hi",
            log_path="/tmp/x.log",
        )
    assert not (tmp_path / "rufino-ingest-bad.plist").exists()


def test_install_rejects_invalid_cron(tmp_path: Path) -> None:
    backend = LaunchdBackend(launchagents_dir=tmp_path, runner=FakeRunner())
    with pytest.raises(ValueError, match="5 fields"):
        backend.install(job_id="j", schedule="bad", cmd="x", log_path="/tmp/l.log")


def test_uninstall_calls_bootout_and_removes_plist(tmp_path: Path) -> None:
    plist = tmp_path / "rufino-ingest-x.plist"
    plist.write_text("<plist/>", encoding="utf-8")
    runner = FakeRunner()
    backend = LaunchdBackend(launchagents_dir=tmp_path, runner=runner)
    backend.uninstall(job_id="rufino-ingest-x")
    assert not plist.exists()
    assert any(c[:2] == ["launchctl", "bootout"] for c in runner.calls)


def test_uninstall_idempotent_if_plist_missing(tmp_path: Path) -> None:
    backend = LaunchdBackend(launchagents_dir=tmp_path, runner=FakeRunner())
    backend.uninstall(job_id="rufino-ingest-never-existed")


def test_list_jobs_filters_rufino_prefix(tmp_path: Path) -> None:
    (tmp_path / "rufino-ingest-a.plist").write_text("x", encoding="utf-8")
    (tmp_path / "rufino-ingest-b.plist").write_text("x", encoding="utf-8")
    (tmp_path / "com.apple.something.plist").write_text("x", encoding="utf-8")
    (tmp_path / "not-a-plist.txt").write_text("x", encoding="utf-8")
    backend = LaunchdBackend(launchagents_dir=tmp_path, runner=FakeRunner())
    jobs = backend.list_jobs()
    assert jobs == ["rufino-ingest-a", "rufino-ingest-b"]


def test_list_jobs_empty_when_dir_missing(tmp_path: Path) -> None:
    backend = LaunchdBackend(launchagents_dir=tmp_path / "nope", runner=FakeRunner())
    assert backend.list_jobs() == []


def test_build_plist_simple_calendar_interval():
    xml = _build_plist(
        job_id="rufino-ingest-x", schedule="0 22 * * *",
        cmd="echo hi", log_path="/tmp/l.log",
    )
    root = ET.fromstring(xml)
    assert root is not None
    assert "<key>StartCalendarInterval</key>" in xml
    assert "<integer>22</integer>" in xml
    assert "<integer>0</integer>" in xml


def test_build_plist_step_minute_maps_to_interval():
    xml = _build_plist(
        job_id="rufino-ingest-x", schedule="*/30 * * * *",
        cmd="echo hi", log_path="/tmp/l.log",
    )
    ET.fromstring(xml)
    assert "<key>StartInterval</key>" in xml
    assert "<integer>1800</integer>" in xml  # 30 * 60


def test_build_plist_step_hour_maps_to_interval():
    xml = _build_plist(
        job_id="rufino-ingest-x", schedule="0 */6 * * *",
        cmd="echo hi", log_path="/tmp/l.log",
    )
    ET.fromstring(xml)
    assert "<key>StartInterval</key>" in xml
    assert "<integer>21600</integer>" in xml  # 6 * 3600


def test_build_plist_unsupported_pattern_raises():
    with pytest.raises(NotImplementedError, match="unsupported"):
        _build_plist(
            job_id="x", schedule="*/15 */6 * * *",
            cmd="echo", log_path="/tmp/l.log",
        )


def test_build_plist_escapes_xml_specials_in_cmd():
    xml = _build_plist(
        job_id="rufino-ingest-x", schedule="0 22 * * *",
        cmd="echo 'a < b && c > d'", log_path="/tmp/l.log",
    )
    ET.fromstring(xml)  # must parse
    assert "a < b && c > d" not in xml
    assert "a &lt; b &amp;&amp; c &gt; d" in xml


def test_build_plist_includes_log_path():
    xml = _build_plist(
        job_id="rufino-ingest-x", schedule="0 22 * * *",
        cmd="echo hi", log_path="/var/log/rufino/x.log",
    )
    ET.fromstring(xml)
    assert "<key>StandardOutPath</key>" in xml
    assert "<string>/var/log/rufino/x.log</string>" in xml
    assert "<key>StandardErrorPath</key>" in xml


def test_build_plist_all_stars_maps_to_one_minute_interval():
    """`* * * * *` is valid cron — every minute. launchd's
    StartCalendarInterval requires at least one key, so we fall back to
    StartInterval=60. validate_cron accepts it, so _build_plist must too."""
    xml = _build_plist(
        job_id="rufino-ingest-x", schedule="* * * * *",
        cmd="echo hi", log_path="/tmp/l.log",
    )
    ET.fromstring(xml)
    assert "<key>StartInterval</key>" in xml
    assert "<integer>60</integer>" in xml


def test_build_plist_minute_pin_with_hour_star():
    """`0 * * * *` runs at minute 0 of every hour. launchd handles this
    natively by leaving Hour off StartCalendarInterval."""
    xml = _build_plist(
        job_id="rufino-ingest-x", schedule="0 * * * *",
        cmd="echo hi", log_path="/tmp/l.log",
    )
    ET.fromstring(xml)
    assert "<key>StartCalendarInterval</key>" in xml
    assert "<key>Minute</key>" in xml
    # Hour is unconstrained — must NOT appear in the calendar block.
    assert "<key>Hour</key>" not in xml


def test_build_plist_hour_pin_with_minute_star():
    """`* 22 * * *` runs every minute during the 22:00 hour."""
    xml = _build_plist(
        job_id="rufino-ingest-x", schedule="* 22 * * *",
        cmd="echo hi", log_path="/tmp/l.log",
    )
    ET.fromstring(xml)
    assert "<key>StartCalendarInterval</key>" in xml
    assert "<key>Hour</key>" in xml
    assert "<integer>22</integer>" in xml
    assert "<key>Minute</key>" not in xml
