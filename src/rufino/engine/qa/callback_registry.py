import copy
import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping


class CallbackRegistryError(Exception):
    """Raised when the persisted callback file is corrupt or unreadable."""


@dataclass(frozen=True)
class PendingCallback:
    question_slug: str
    adapter_name: str
    adapter_state: Mapping  # MappingProxyType after register/get; readonly view


class CallbackRegistry:
    """JSON-persisted map of pending Q&A callbacks. Atomic-write safe."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._data: dict[str, dict] = {}
        if path.exists():
            try:
                self._data = json.loads(path.read_text())
            except json.JSONDecodeError as e:
                raise CallbackRegistryError(
                    f"Callback registry at {path} is corrupt: {e}"
                ) from e

    def register(self, cb: PendingCallback) -> None:
        # Deep-copy the adapter_state so later mutations by the caller can't
        # leak into the persisted view. json round-trip also validates that
        # the state is JSON-serializable now rather than at flush time.
        state_copy = json.loads(json.dumps(dict(cb.adapter_state)))
        self._data[cb.question_slug] = {
            "adapter_name": cb.adapter_name,
            "adapter_state": state_copy,
        }
        self._flush()

    def get(self, slug: str) -> PendingCallback | None:
        raw = self._data.get(slug)
        if raw is None:
            return None
        return PendingCallback(
            question_slug=slug,
            adapter_name=raw["adapter_name"],
            adapter_state=MappingProxyType(copy.deepcopy(raw["adapter_state"])),
        )

    def consume(self, slug: str) -> PendingCallback | None:
        cb = self.get(slug)
        if cb is not None:
            self._data.pop(slug, None)
            self._flush()
        return cb

    def _flush(self) -> None:
        """Atomic write: stage to .tmp then rename."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(self._data, indent=2))
        tmp.replace(self._path)
