"""macOS launchd backend — installs/uninstalls per-user LaunchAgents.

Maps the wizard's cron expression to either StartCalendarInterval (simple
`MIN HOUR * * *` forms) or StartInterval (step forms `*/N` in the minute or
hour field). More exotic cron patterns are rejected up front rather than
silently mis-translated — the wizard is constrained to portable schedules.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence
from xml.sax.saxutils import escape as _xml_escape

from rufino.runtime.scheduler import validate_cron

RunFn = Callable[[Sequence[str]], subprocess.CompletedProcess]


def _default_run(cmd: Sequence[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        list(cmd), capture_output=True, text=True, check=False
    )


@dataclass
class LaunchdBackend:
    launchagents_dir: Path = field(
        default_factory=lambda: Path.home() / "Library" / "LaunchAgents"
    )
    runner: RunFn = field(default=_default_run)

    def install(
        self, *, job_id: str, schedule: str, cmd: str, log_path: str
    ) -> None:
        validate_cron(schedule)
        plist_xml = _build_plist(
            job_id=job_id, schedule=schedule, cmd=cmd, log_path=log_path
        )
        self.launchagents_dir.mkdir(parents=True, exist_ok=True)
        plist_path = self.launchagents_dir / f"{job_id}.plist"
        plist_path.write_text(plist_xml, encoding="utf-8")
        uid = os.getuid()
        # Idempotent: bootout if already loaded (ignore failure — service may
        # not be loaded yet).
        self.runner(["launchctl", "bootout", f"gui/{uid}/{job_id}"])
        result = self.runner(
            ["launchctl", "bootstrap", f"gui/{uid}", str(plist_path)]
        )
        if result.returncode != 0:
            plist_path.unlink(missing_ok=True)
            raise RuntimeError(
                f"launchctl bootstrap failed for {job_id}: "
                f"exit={result.returncode} stderr={result.stderr!r}"
            )

    def uninstall(self, *, job_id: str) -> None:
        uid = os.getuid()
        self.runner(["launchctl", "bootout", f"gui/{uid}/{job_id}"])
        plist_path = self.launchagents_dir / f"{job_id}.plist"
        plist_path.unlink(missing_ok=True)

    def list_jobs(self) -> list[str]:
        if not self.launchagents_dir.exists():
            return []
        return sorted(p.stem for p in self.launchagents_dir.glob("rufino-*.plist"))


def _build_plist(
    *, job_id: str, schedule: str, cmd: str, log_path: str
) -> str:
    parts = schedule.strip().split()
    minute, hour, dom, month, dow = parts
    rest_stars = dom == "*" and month == "*" and dow == "*"

    # Step syntax `*/N` only maps cleanly to launchd's StartInterval when the
    # step is in the minute or hour field alone — combining step + concrete
    # cron pins isn't expressible without a cron daemon.
    if minute.startswith("*/") and hour == "*" and rest_stars:
        interval_xml = _interval_block(int(minute[2:]) * 60)
    elif minute == "0" and hour.startswith("*/") and rest_stars:
        interval_xml = _interval_block(int(hour[2:]) * 3600)
    elif all(_is_calendar_field(p) for p in parts):
        cal_lines: list[str] = []
        if minute != "*":
            cal_lines.append(_kv("Minute", int(minute)))
        if hour != "*":
            cal_lines.append(_kv("Hour", int(hour)))
        if dom != "*":
            cal_lines.append(_kv("Day", int(dom)))
        if month != "*":
            cal_lines.append(_kv("Month", int(month)))
        if dow != "*":
            cal_lines.append(_kv("Weekday", int(dow)))
        if not cal_lines:
            # `* * * * *` — every minute. StartCalendarInterval needs at
            # least one key, so fall back to StartInterval=60.
            interval_xml = _interval_block(60)
        else:
            interval_xml = (
                "    <key>StartCalendarInterval</key>\n"
                "    <dict>\n" + "\n".join(cal_lines) + "\n    </dict>"
            )
    else:
        raise NotImplementedError(
            f"unsupported cron pattern for launchd: {schedule!r}"
        )

    label = _xml_escape(job_id)
    cmd_esc = _xml_escape(cmd)
    log_esc = _xml_escape(log_path)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>-c</string>
        <string>{cmd_esc}</string>
    </array>
{interval_xml}
    <key>StandardOutPath</key>
    <string>{log_esc}</string>
    <key>StandardErrorPath</key>
    <string>{log_esc}</string>
</dict>
</plist>
"""


def _is_calendar_field(part: str) -> bool:
    """A field is calendar-mappable when it's `*` or a bare positive int."""
    return part == "*" or part.isdigit()


def _kv(key: str, value: int) -> str:
    return f"        <key>{key}</key>\n        <integer>{value}</integer>"


def _interval_block(seconds: int) -> str:
    return f"    <key>StartInterval</key>\n    <integer>{seconds}</integer>"
