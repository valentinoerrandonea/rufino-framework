import subprocess
from dataclasses import dataclass
from typing import Any


@dataclass
class PushChannel:
    platform: str  # "Darwin" or "Linux"

    def deliver(self, *, config: dict[str, Any], content: str) -> None:
        title = config.get("title", "Rufino")
        if self.platform == "Darwin":
            cmd = [
                "osascript", "-e",
                f'display notification "{content}" with title "{title}"',
            ]
        elif self.platform == "Linux":
            cmd = ["notify-send", title, content]
        else:
            raise NotImplementedError(f"No push backend for {self.platform!r}")
        subprocess.run(cmd, check=True)
