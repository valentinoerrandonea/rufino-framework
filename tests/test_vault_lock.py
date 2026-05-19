import multiprocessing
import time
from pathlib import Path

import pytest

from rufino.runtime.vault_lock import VaultLockedError, vault_lock


def _hold_lock(vault: str, seconds: float) -> None:
    with vault_lock(Path(vault)):
        time.sleep(seconds)


def test_vault_lock_blocks_second_acquirer(tmp_path: Path) -> None:
    vault = tmp_path / "v"
    vault.mkdir()
    p = multiprocessing.Process(target=_hold_lock, args=(str(vault), 1.5))
    p.start()
    time.sleep(0.3)
    try:
        with pytest.raises(VaultLockedError):
            with vault_lock(vault, wait=False):
                pass
    finally:
        p.join()


def test_vault_lock_released_on_context_exit(tmp_path: Path) -> None:
    vault = tmp_path / "v"
    vault.mkdir()
    with vault_lock(vault):
        pass
    with vault_lock(vault):
        pass


def test_vault_lock_creates_dotrufino_dir(tmp_path: Path) -> None:
    vault = tmp_path / "v"
    vault.mkdir()
    with vault_lock(vault):
        assert (vault / ".rufino" / "lock").exists()


def test_vault_lock_creates_vault_if_missing(tmp_path: Path) -> None:
    """``process-batch`` and friends are documented as creating the vault
    on first run; the lock primitive must not break that flow by demanding
    the directory already exists."""
    fresh = tmp_path / "fresh-vault"
    with vault_lock(fresh):
        assert (fresh / ".rufino" / "lock").exists()
