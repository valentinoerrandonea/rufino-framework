import subprocess
from pathlib import Path

import pytest

from rufino.runtime.scheduler.cron import (
    CronBackend,
    _entry_for_job,
    _filter_other_entries,
)


class FakeCrontab:
    """Stand-in for the `crontab` binary. Holds an in-memory crontab string."""

    def __init__(self, initial: str = "") -> None:
        self.content = initial
        self.calls: list[tuple[list[str], str | None]] = []

    def __call__(self, cmd, *, input=None):
        cmd = list(cmd)
        self.calls.append((cmd, input))
        if cmd == ["crontab", "-l"]:
            if self.content:
                return subprocess.CompletedProcess(
                    cmd, 0, stdout=self.content, stderr=""
                )
            # crontab -l on empty user crontab exits 1 with stderr "no crontab"
            return subprocess.CompletedProcess(
                cmd, 1, stdout="", stderr="no crontab for user"
            )
        if cmd == ["crontab", "-"]:
            self.content = input or ""
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        if cmd == ["crontab", "-r"]:
            self.content = ""
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        raise AssertionError(f"unexpected crontab cmd: {cmd}")


def test_install_writes_entry_with_marker(tmp_path: Path) -> None:
    fc = FakeCrontab(initial="")
    backend = CronBackend(runner=fc)
    backend.install(
        job_id="rufino-ingest-x",
        schedule="0 22 * * *",
        cmd="echo hi",
        log_path=str(tmp_path / "x.log"),
    )
    assert "# rufino-job:rufino-ingest-x" in fc.content
    assert "0 22 * * *" in fc.content


def test_install_replaces_existing_entry(tmp_path: Path) -> None:
    initial = (
        "0 10 * * * /bin/echo other # rufino-job:rufino-ingest-x\n"
        "0 5 * * * /bin/echo unrelated\n"
    )
    fc = FakeCrontab(initial=initial)
    backend = CronBackend(runner=fc)
    backend.install(
        job_id="rufino-ingest-x",
        schedule="0 22 * * *",
        cmd="echo new",
        log_path=str(tmp_path / "x.log"),
    )
    lines = fc.content.strip().split("\n")
    rufino_lines = [l for l in lines if "rufino-job:rufino-ingest-x" in l]
    assert len(rufino_lines) == 1
    assert "echo new" in rufino_lines[0]
    # unrelated entry preserved
    assert any("# rufino-job:" not in l and "unrelated" in l for l in lines)


def test_install_rejects_invalid_cron():
    backend = CronBackend(runner=FakeCrontab())
    with pytest.raises(ValueError, match="5 fields"):
        backend.install(
            job_id="x", schedule="bad", cmd="echo", log_path="/tmp/x.log"
        )


def test_install_preserves_unrelated_entries():
    initial = (
        "30 3 * * * /usr/bin/some-other-cron\n"
        "@reboot /bin/something\n"
    )
    fc = FakeCrontab(initial=initial)
    backend = CronBackend(runner=fc)
    backend.install(
        job_id="rufino-ingest-x",
        schedule="0 22 * * *",
        cmd="echo hi",
        log_path="/tmp/x.log",
    )
    assert "/usr/bin/some-other-cron" in fc.content
    assert "@reboot /bin/something" in fc.content
    assert "rufino-job:rufino-ingest-x" in fc.content


def test_uninstall_removes_marked_entry():
    initial = (
        "0 22 * * * echo hi # rufino-job:rufino-ingest-x\n"
        "0 5 * * * /bin/echo unrelated\n"
    )
    fc = FakeCrontab(initial=initial)
    backend = CronBackend(runner=fc)
    backend.uninstall(job_id="rufino-ingest-x")
    assert "rufino-job:rufino-ingest-x" not in fc.content
    assert "unrelated" in fc.content


def test_uninstall_idempotent_when_missing():
    fc = FakeCrontab(initial="0 5 * * * /bin/echo unrelated\n")
    backend = CronBackend(runner=fc)
    # Should not raise — uninstall of unknown job is a noop.
    backend.uninstall(job_id="rufino-ingest-nope")
    assert "unrelated" in fc.content


def test_uninstall_when_user_has_no_crontab():
    fc = FakeCrontab(initial="")  # crontab -l exits 1
    backend = CronBackend(runner=fc)
    backend.uninstall(job_id="rufino-ingest-x")  # noop, no exception


def test_list_jobs_returns_rufino_ids_only():
    initial = (
        "0 22 * * * echo a # rufino-job:rufino-ingest-a\n"
        "0 23 * * * echo b # rufino-job:rufino-ingest-b\n"
        "0 5 * * * /bin/echo unrelated\n"
    )
    fc = FakeCrontab(initial=initial)
    backend = CronBackend(runner=fc)
    assert backend.list_jobs() == ["rufino-ingest-a", "rufino-ingest-b"]


def test_list_jobs_empty_when_no_crontab():
    fc = FakeCrontab(initial="")
    backend = CronBackend(runner=fc)
    assert backend.list_jobs() == []


def test_entry_for_job_uses_marker_suffix(tmp_path: Path):
    line = _entry_for_job(
        job_id="rufino-ingest-x",
        schedule="0 22 * * *",
        cmd="echo hi",
        log_path=str(tmp_path / "x.log"),
    )
    assert line.endswith("# rufino-job:rufino-ingest-x\n")
    assert "0 22 * * *" in line
    assert "echo hi" in line
    assert ">>" in line and "2>&1" in line  # log redirection appended


def test_entry_for_job_rejects_newlines_in_cmd():
    with pytest.raises(ValueError, match="newline"):
        _entry_for_job(
            job_id="j",
            schedule="0 22 * * *",
            cmd="echo hi\nrm -rf /",
            log_path="/tmp/x.log",
        )


def test_filter_other_entries_drops_only_targeted_marker():
    content = (
        "0 22 * * * echo a # rufino-job:rufino-ingest-a\n"
        "0 23 * * * echo b # rufino-job:rufino-ingest-b\n"
        "0 5 * * * /bin/echo unrelated\n"
    )
    out = _filter_other_entries(content, job_id="rufino-ingest-a")
    assert "rufino-ingest-a" not in out
    assert "rufino-ingest-b" in out
    assert "unrelated" in out
