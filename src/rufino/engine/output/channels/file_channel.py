from dataclasses import dataclass
from pathlib import Path
from typing import Any


class PathTraversalError(Exception):
    """Raised when a delivery path resolves outside the vault root."""


@dataclass
class FileChannel:
    vault_root: Path

    def deliver(self, *, config: dict[str, Any], content: str) -> None:
        candidate = self.vault_root / config["path"]
        resolved = candidate.resolve()
        root = self.vault_root.resolve()
        if root != resolved and root not in resolved.parents:
            raise PathTraversalError(
                f"delivery path escapes vault_root: {config['path']!r}"
            )
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content)
