import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PendingCallback:
    question_slug: str
    adapter_name: str
    adapter_state: dict


class CallbackRegistry:
    """JSON-persisted map of pending Q&A callbacks."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._data: dict[str, dict] = {}
        if path.exists():
            self._data = json.loads(path.read_text())

    def register(self, cb: PendingCallback) -> None:
        self._data[cb.question_slug] = {
            "adapter_name": cb.adapter_name,
            "adapter_state": cb.adapter_state,
        }
        self._flush()

    def get(self, slug: str) -> PendingCallback | None:
        raw = self._data.get(slug)
        if raw is None:
            return None
        return PendingCallback(
            question_slug=slug,
            adapter_name=raw["adapter_name"],
            adapter_state=raw["adapter_state"],
        )

    def consume(self, slug: str) -> PendingCallback | None:
        cb = self.get(slug)
        if cb is not None:
            self._data.pop(slug, None)
            self._flush()
        return cb

    def _flush(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, indent=2))
