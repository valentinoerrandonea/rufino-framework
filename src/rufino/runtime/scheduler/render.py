import re
from dataclasses import dataclass
from typing import Protocol
from xml.sax.saxutils import escape as _xml_escape

_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


@dataclass(frozen=True)
class ScheduledJob:
    """A scheduled job definition. OS-agnostic."""
    name: str
    cron: str  # standard 5-field cron expression
    command: str

    def __post_init__(self) -> None:
        for field_name, value in (("name", self.name), ("command", self.command)):
            if "\n" in value or "\r" in value:
                raise ValueError(
                    f"ScheduledJob.{field_name} must not contain newlines: {value!r}"
                )
        if not _NAME_RE.match(self.name):
            raise ValueError(
                f"ScheduledJob.name must match {_NAME_RE.pattern}, got {self.name!r}"
            )
        parts = self.cron.split()
        if len(parts) != 5:
            raise ValueError(
                f"cron must have 5 fields, got {len(parts)}: {self.cron!r}"
            )


class Scheduler(Protocol):
    """Abstract scheduler. Renders a ScheduledJob to OS-specific format."""

    def render(self, job: ScheduledJob) -> str: ...


class LaunchdScheduler:
    """macOS launchd backend. Renders ScheduledJob to .plist XML."""

    def render(self, job: ScheduledJob) -> str:
        minute, hour, day, month, weekday = job.cron.split()
        if any(c in (minute, hour) for c in ("*", "/", ",", "-")):
            raise NotImplementedError(
                f"LaunchdScheduler supports only simple cron expressions; got {job.cron!r}"
            )
        m, h = int(minute), int(hour)
        if not (0 <= m <= 59 and 0 <= h <= 23):
            raise ValueError(
                f"cron out of range: hour={h} minute={m} (got {job.cron!r})"
            )
        name_xml = _xml_escape(job.name)
        command_xml = _xml_escape(job.command)
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{name_xml}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>-c</string>
        <string>{command_xml}</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>{h}</integer>
        <key>Minute</key>
        <integer>{m}</integer>
    </dict>
</dict>
</plist>
"""


class CronScheduler:
    """Linux cron backend. Renders ScheduledJob to a crontab line."""

    def render(self, job: ScheduledJob) -> str:
        return f"{job.cron} {job.command} # rufino-job:{job.name}\n"


def pick_scheduler_for_os(os_name: str) -> Scheduler:
    """Return the appropriate Scheduler for the given OS (output of platform.system())."""
    if os_name == "Darwin":
        return LaunchdScheduler()
    if os_name == "Linux":
        return CronScheduler()
    raise NotImplementedError(f"No scheduler backend for OS {os_name!r}")
