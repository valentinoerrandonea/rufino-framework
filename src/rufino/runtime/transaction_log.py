import json
import shutil
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable, Any


@dataclass(frozen=True)
class LogEntry:
    """A single bootstrap operation + how to revert it."""
    op: str          # "mkdir" | "write" | "keychain_add" | "plist_install" | ...
    target: str      # what the op acted on (path, service+account, plist name, ...)
    rollback: str    # canonical name of the inverse: "rmdir" | "delete" | "keychain_delete" | ...

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


# Built-in rollback registry. Adapters/runtime can register more.
_ROLLBACK_REGISTRY: dict[str, Callable[[str], None]] = {}


def register_rollback(name: str, fn: Callable[[str], None]) -> None:
    _ROLLBACK_REGISTRY[name] = fn


def _rmdir(target: str) -> None:
    p = Path(target)
    if p.exists():
        shutil.rmtree(p) if p.is_dir() else p.unlink()


def _delete(target: str) -> None:
    p = Path(target)
    if p.exists():
        p.unlink()


register_rollback("rmdir", _rmdir)
register_rollback("delete", _delete)


class TransactionLog:
    """Append-only log of bootstrap operations + their rollbacks. Persisted as JSON."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._entries: list[LogEntry] = []

    def record(self, entry: LogEntry) -> None:
        self._entries.append(entry)
        self._flush()

    def entries(self) -> list[LogEntry]:
        return list(self._entries)

    def rollback(self) -> None:
        """Execute rollback for each entry in REVERSE order."""
        for entry in reversed(self._entries):
            handler = _ROLLBACK_REGISTRY.get(entry.rollback)
            if handler is None:
                raise RuntimeError(f"No rollback handler registered for {entry.rollback!r}")
            handler(entry.target)

    @classmethod
    def load(cls, path: Path) -> "TransactionLog":
        log = cls(path)
        if path.exists():
            raw = json.loads(path.read_text())
            log._entries = [LogEntry(**e) for e in raw]
        return log

    def _flush(self) -> None:
        self._path.write_text(json.dumps([e.to_dict() for e in self._entries], indent=2))


def apply_and_log(
    log: TransactionLog,
    *,
    op: str,
    target: str,
    apply_fn: Callable[[], Any],
    rollback: str,
) -> Any:
    """Execute apply_fn() and only record the log entry on success.

    If apply_fn() raises, the log is unmodified and the exception propagates.
    """
    result = apply_fn()
    log.record(LogEntry(op=op, target=target, rollback=rollback))
    return result
