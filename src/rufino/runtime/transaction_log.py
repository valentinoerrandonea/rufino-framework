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
        """Execute rollback for each entry in REVERSE order.

        Idempotent: each successful handler pops its entry and flushes the log,
        so re-running rollback() on a fully-rolled-back log is a no-op.
        If a handler raises, remaining entries stay in the log and a subsequent
        rollback() retries from where it stopped.
        """
        while self._entries:
            entry = self._entries[-1]
            handler = _ROLLBACK_REGISTRY.get(entry.rollback)
            if handler is None:
                raise RuntimeError(f"No rollback handler registered for {entry.rollback!r}")
            handler(entry.target)
            self._entries.pop()
            self._flush()

    @classmethod
    def load(cls, path: Path) -> "TransactionLog":
        log = cls(path)
        if not path.exists():
            return log
        try:
            raw = json.loads(path.read_text())
            log._entries = [LogEntry(**e) for e in raw]
        except (json.JSONDecodeError, TypeError) as e:
            raise RuntimeError(f"Transaction log at {path} is corrupted: {e}") from e
        return log

    def _flush(self) -> None:
        """Atomic write: stage to .tmp then rename."""
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps([e.to_dict() for e in self._entries], indent=2))
        tmp.replace(self._path)


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
