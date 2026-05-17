from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class FileChannel:
    vault_root: Path

    def deliver(self, *, config: dict[str, Any], content: str) -> None:
        path = self.vault_root / config["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
