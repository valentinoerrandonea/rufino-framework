import json
import os
import shutil
import threading
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
_REGISTRY_LOCK = threading.Lock()


def register_rollback(name: str, fn: Callable[[str], None]) -> None:
    with _REGISTRY_LOCK:
        _ROLLBACK_REGISTRY[name] = fn


def _rmdir(target: str) -> None:
    p = Path(target)
    if p.exists():
        shutil.rmtree(p) if p.is_dir() else p.unlink()


def _delete(target: str) -> None:
    p = Path(target)
    if p.exists():
        p.unlink()


def _rmdir_if_empty(target: str) -> None:
    p = Path(target)
    if p.exists() and p.is_dir() and not any(p.iterdir()):
        p.rmdir()


def _keychain_delete(target: str) -> None:
    """Delete a keychain entry. target encodes 'service\x00account'."""
    try:
        import keyring
    except ImportError:
        return
    if "\x00" not in target:
        return
    service, account = target.split("\x00", 1)
    try:
        keyring.delete_password(service, account)
    except Exception:
        pass


def _plist_uninstall(target: str) -> None:
    """Unload + remove a launchd plist. target is the absolute plist path."""
    import subprocess
    p = Path(target)
    if p.exists():
        subprocess.run(["launchctl", "unload", str(p)], check=False)
        p.unlink()


register_rollback("rmdir", _rmdir)
register_rollback("delete", _delete)
register_rollback("rmdir_if_empty", _rmdir_if_empty)
register_rollback("keychain_delete", _keychain_delete)
register_rollback("plist_uninstall", _plist_uninstall)


class TransactionLog:
    """Append-only log of bootstrap operations + their rollbacks. Persisted as JSON."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._entries: list[LogEntry] = []

    def record(self, entry: LogEntry) -> None:
        if entry.rollback not in _ROLLBACK_REGISTRY:
            raise ValueError(
                f"unknown rollback handler {entry.rollback!r}; "
                f"call register_rollback() first"
            )
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
        """Atomic write: stage to .tmp, fsync, rename, fsync parent dir."""
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        data = json.dumps([e.to_dict() for e in self._entries], indent=2)
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        tmp.replace(self._path)
        try:
            dir_fd = os.open(self._path.parent, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(dir_fd)
        except OSError:
            pass
        finally:
            os.close(dir_fd)


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
