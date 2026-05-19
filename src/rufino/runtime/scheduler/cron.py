"""Linux cron backend — installs/uninstalls user crontab entries with a marker.

Every entry written by Rufino carries a `# rufino-job:<job_id>` suffix, which
lets `_filter_other_entries` strip a single entry on uninstall without touching
the user's own crontab lines or other Rufino jobs.
"""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass, field
from typing import Callable, Sequence

from rufino.runtime.scheduler import validate_cron

_MARKER_PREFIX = "# rufino-job:"

CrontabRunner = Callable[..., subprocess.CompletedProcess]


def _default_runner(cmd: Sequence[str], *, input: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        list(cmd), input=input, capture_output=True, text=True, check=False
    )


@dataclass
class CronBackend:
    runner: CrontabRunner = field(default=_default_runner)

    def install(
        self, *, job_id: str, schedule: str, cmd: str, log_path: str
    ) -> None:
        validate_cron(schedule)
        entry = _entry_for_job(
            job_id=job_id, schedule=schedule, cmd=cmd, log_path=log_path
        )
        current = self._read_crontab()
        filtered = _filter_other_entries(current, job_id=job_id)
        new_content = filtered + entry
        self._write_crontab(new_content)

    def uninstall(self, *, job_id: str) -> None:
        current = self._read_crontab()
        if not current:
            return
        new_content = _filter_other_entries(current, job_id=job_id)
        if new_content == current:
            return
        self._write_crontab(new_content)

    def list_jobs(self) -> list[str]:
        current = self._read_crontab()
        jobs: list[str] = []
        for line in current.splitlines():
            marker_idx = line.find(_MARKER_PREFIX)
            if marker_idx == -1:
                continue
            jobs.append(line[marker_idx + len(_MARKER_PREFIX):].strip())
        return sorted(jobs)

    def _read_crontab(self) -> str:
        result = self.runner(["crontab", "-l"])
        if result.returncode != 0:
            return ""
        return result.stdout

    def _write_crontab(self, content: str) -> None:
        result = self.runner(["crontab", "-"], input=content)
        if result.returncode != 0:
            raise RuntimeError(
                f"crontab write failed: exit={result.returncode} stderr={result.stderr!r}"
            )


def _entry_for_job(
    *, job_id: str, schedule: str, cmd: str, log_path: str
) -> str:
    if "\n" in cmd or "\r" in cmd:
        raise ValueError(f"cron cmd must not contain newlines: {cmd!r}")
    if "\n" in job_id or "\r" in job_id:
        raise ValueError(f"cron job_id must not contain newlines: {job_id!r}")
    redirected = f"{cmd} >> {shlex.quote(log_path)} 2>&1"
    return f"{schedule} {redirected} {_MARKER_PREFIX}{job_id}\n"


def _filter_other_entries(content: str, *, job_id: str) -> str:
    marker = f"{_MARKER_PREFIX}{job_id}"
    kept = [
        line for line in content.splitlines(keepends=True)
        if marker not in line
    ]
    out = "".join(kept)
    if out and not out.endswith("\n"):
        out += "\n"
    return out
