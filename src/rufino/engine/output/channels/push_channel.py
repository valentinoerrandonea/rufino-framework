import subprocess
from dataclasses import dataclass
from typing import Any


def _escape_applescript(value: str) -> str:
    """Escape backslashes and double quotes for safe embedding in AppleScript strings."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


@dataclass
class PushChannel:
    platform: str  # "Darwin" or "Linux"

    def deliver(self, *, config: dict[str, Any], content: str) -> None:
        title = config.get("title", "Rufino")
        if self.platform == "Darwin":
            safe_content = _escape_applescript(content)
            safe_title = _escape_applescript(title)
            cmd = [
                "osascript", "-e",
                f'display notification "{safe_content}" with title "{safe_title}"',
            ]
        elif self.platform == "Linux":
            cmd = ["notify-send", title, content]
        else:
            raise NotImplementedError(f"No push backend for {self.platform!r}")
        subprocess.run(cmd, check=True)
