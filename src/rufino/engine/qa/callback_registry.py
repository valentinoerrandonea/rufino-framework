import copy
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

try:
    import fcntl  # POSIX-only
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore


_log = logging.getLogger(__name__)


class CallbackRegistryError(Exception):
    """Raised when the persisted callback file is corrupt or unreadable."""


@dataclass(frozen=True)
class PendingCallback:
    question_slug: str
    adapter_name: str
    adapter_state: Mapping  # recursively-frozen MappingProxyType after register/get


def _freeze(value: Any) -> Any:
    """Recursively wrap dicts in MappingProxyType so nested state is read-only.

    Mirrors the `_freeze` helper in `output/manifest.py` for consistency across
    primitives.
    """
    if isinstance(value, dict):
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(v) for v in value)
    return value


class CallbackRegistry:
    """JSON-persisted map of pending Q&A callbacks.

    Persistence guarantees:
    - Writes are atomic within a single process (tmp + rename).
    - A POSIX advisory file lock (`<path>.lock`) serializes read-modify-write
      cycles across processes when `fcntl` is available. On platforms without
      `fcntl` (Windows) the lock is a no-op and concurrent writers may stomp
      each other — single-process use is safe regardless.
    - File mode is 0600 (owner-only) so `adapter_state` containing tokens or
      paths to private files is not leaked to other users on shared hosts.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock_path = path.with_suffix(path.suffix + ".lock")
        self._data: dict[str, dict] = {}
        if path.exists():
            try:
                self._data = json.loads(path.read_text())
            except json.JSONDecodeError as e:
                raise CallbackRegistryError(
                    f"Callback registry at {path} is corrupt: {e}"
                ) from e

    def register(self, cb: PendingCallback) -> None:
        with self._locked():
            # Deep-copy the adapter_state so later mutations by the caller can't
            # leak into the persisted view. json round-trip also validates that
            # the state is JSON-serializable now rather than at flush time.
            state_copy = json.loads(json.dumps(dict(cb.adapter_state)))
            self._reload_unlocked()
            self._data[cb.question_slug] = {
                "adapter_name": cb.adapter_name,
                "adapter_state": state_copy,
            }
            self._flush_unlocked()

    def get(self, slug: str) -> PendingCallback | None:
        raw = self._data.get(slug)
        if raw is None:
            return None
        return PendingCallback(
            question_slug=slug,
            adapter_name=raw["adapter_name"],
            adapter_state=_freeze(copy.deepcopy(raw["adapter_state"])),
        )

    def delete(self, slug: str) -> None:
        """Remove a callback without returning it (cheaper than `consume`)."""
        with self._locked():
            self._reload_unlocked()
            if self._data.pop(slug, None) is not None:
                self._flush_unlocked()

    def consume(self, slug: str) -> PendingCallback | None:
        cb = self.get(slug)
        if cb is not None:
            self.delete(slug)
        return cb

    def _flush_unlocked(self) -> None:
        """Atomic write: stage to .tmp, chmod 0600, then rename."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(self._data, indent=2))
        try:
            os.chmod(tmp, 0o600)
        except OSError:  # pragma: no cover — non-POSIX
            pass
        tmp.replace(self._path)

    def _reload_unlocked(self) -> None:
        """Re-read disk state while holding the lock so concurrent writers
        from other processes don't get stomped."""
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text())
            except json.JSONDecodeError as e:
                raise CallbackRegistryError(
                    f"Callback registry at {self._path} is corrupt: {e}"
                ) from e

    def _locked(self):
        return _FileLock(self._lock_path) if fcntl is not None else _NullLock()


class _FileLock:
    """POSIX advisory exclusive lock via a sidecar lockfile."""
    def __init__(self, path: Path) -> None:
        self._path = path
        self._fd: int | None = None

    def __enter__(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._fd = os.open(self._path, os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(self._fd, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        if self._fd is not None:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            finally:
                os.close(self._fd)
                self._fd = None


class _NullLock:  # pragma: no cover — non-POSIX fallback
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None
