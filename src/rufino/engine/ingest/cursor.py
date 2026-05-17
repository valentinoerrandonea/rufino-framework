import json
from pathlib import Path


class CursorStore:
    """Per-adapter cursor (last-processed marker). Persisted as JSON."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._data: dict[str, str] = {}
        if path.exists():
            self._data = json.loads(path.read_text(encoding="utf-8"))

    def get(self, adapter_name: str) -> str | None:
        return self._data.get(adapter_name)

    def set(self, adapter_name: str, cursor: str) -> None:
        self._data[adapter_name] = cursor
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
