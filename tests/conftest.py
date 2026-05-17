import pytest
import tempfile
from pathlib import Path


@pytest.fixture
def tmp_vault(tmp_path: Path) -> Path:
    """Vault path temporal limpio para cada test."""
    vault = tmp_path / "vault"
    vault.mkdir()
    return vault


@pytest.fixture
def tmp_rufino_home(tmp_path: Path, monkeypatch) -> Path:
    """~/.rufino temporal aislado del filesystem real del user."""
    home = tmp_path / ".rufino"
    home.mkdir()
    monkeypatch.setenv("RUFINO_HOME", str(home))
    return home
