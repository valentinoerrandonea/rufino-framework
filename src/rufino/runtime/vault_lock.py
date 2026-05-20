import fcntl
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class VaultLockedError(RuntimeError):
    """Raised when the vault advisory lock is held by another process."""


@contextmanager
def vault_lock(vault_root: Path, *, wait: bool = False) -> Iterator[None]:
    """Acquire a flock-based advisory lock at <vault>/.rufino/lock.

    If wait=False (default), raises VaultLockedError immediately if held.
    If wait=True, blocks until acquired.
    """
    lock_dir = vault_root / ".rufino"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / "lock"
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        flags = fcntl.LOCK_EX if wait else fcntl.LOCK_EX | fcntl.LOCK_NB
        try:
            fcntl.flock(fd, flags)
        except BlockingIOError as e:
            raise VaultLockedError(
                f"Vault {vault_root} is locked by another process. "
                f"Esperá a que termine y reintentá."
            ) from e
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)
