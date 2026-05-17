from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ScheduledJob:
    """A scheduled job definition. OS-agnostic."""
    name: str
    cron: str  # standard 5-field cron expression
    command: str


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
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{job.name}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>-c</string>
        <string>{job.command}</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>{int(hour)}</integer>
        <key>Minute</key>
        <integer>{int(minute)}</integer>
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
