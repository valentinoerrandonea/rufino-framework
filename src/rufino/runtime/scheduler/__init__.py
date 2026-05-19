"""Scheduler primitive: cron-expression validation + OS-specific job backends.

Re-exports legacy `render.py` symbols (ScheduledJob + plist/crontab renderers) so
existing call sites keep working, and exposes the v0.2 backend protocol with
install/uninstall/list_jobs operations.
"""

from __future__ import annotations

import platform
from typing import Protocol

from rufino.runtime.scheduler.render import (
    CronScheduler,
    LaunchdScheduler,
    ScheduledJob,
    Scheduler,
    pick_scheduler_for_os,
)

__all__ = [
    "CronScheduler",
    "LaunchdScheduler",
    "ScheduledJob",
    "Scheduler",
    "SchedulerBackend",
    "get_backend",
    "pick_scheduler_for_os",
    "validate_cron",
]


class SchedulerBackend(Protocol):
    """OS-specific scheduler backend protocol."""

    def install(
        self, *, job_id: str, schedule: str, cmd: str, log_path: str
    ) -> None: ...

    def uninstall(self, *, job_id: str) -> None: ...

    def list_jobs(self) -> list[str]: ...


def get_backend() -> SchedulerBackend:
    system = platform.system()
    if system == "Darwin":
        from rufino.runtime.scheduler.launchd import LaunchdBackend
        return LaunchdBackend()
    if system == "Linux":
        from rufino.runtime.scheduler.cron import CronBackend
        return CronBackend()
    raise NotImplementedError(f"No scheduler backend for {system!r}")


_CRON_RANGES: tuple[tuple[int, int], ...] = (
    (0, 59),  # minute
    (0, 23),  # hour
    (1, 31),  # day-of-month
    (1, 12),  # month
    (0, 6),   # day-of-week
)


def validate_cron(expr: str) -> None:
    """Validate a 5-field cron expression. Raises ValueError on any malformation.

    Accepts: '*', integer in range, '*/N' step syntax. Anything else (lists,
    ranges, named months) is rejected for v0.2 — keeps the wizard's manifests
    portable across launchd's StartCalendarInterval and crontab.
    """
    parts = expr.strip().split()
    if len(parts) != 5:
        raise ValueError(f"Cron must have 5 fields, got {len(parts)}: {expr!r}")
    for i, (part, (lo, hi)) in enumerate(zip(parts, _CRON_RANGES)):
        if part == "*":
            continue
        if part.startswith("*/"):
            try:
                step = int(part[2:])
            except ValueError as e:
                raise ValueError(
                    f"Invalid step in field {i}: {part!r}"
                ) from e
            if step <= 0:
                raise ValueError(f"Cron step must be positive in field {i}: {part!r}")
            continue
        try:
            v = int(part)
        except ValueError as e:
            raise ValueError(f"Invalid cron field {i}: {part!r}") from e
        if not (lo <= v <= hi):
            raise ValueError(
                f"Cron field {i} value {v} out of range [{lo},{hi}]"
            )
