import pytest
from pathlib import Path
from rufino.engine.memory_loop.installer import (
    install_memory_loop,
    InstallationError,
)
from rufino.runtime.transaction_log import TransactionLog


FIXTURE = Path(__file__).parent / "fixtures" / "adapters" / "memory-loop-facultad"


def test_install_creates_hooks_and_substitutes(tmp_path: Path, tmp_vault: Path):
    claude_home = tmp_path / ".claude"
    claude_home.mkdir()
    tx_log = TransactionLog(tmp_path / "tx.json")

    install_memory_loop(
        adapter_dir=FIXTURE,
        claude_home=claude_home,
        vault_path=tmp_vault,
        log=tx_log,
    )

    init_hook = claude_home / "hooks" / "rufino-memory-loop-init.sh"
    stop_hook = claude_home / "hooks" / "rufino-memory-loop-stop.sh"
    assert init_hook.exists()
    assert stop_hook.exists()

    init_content = init_hook.read_text()
    assert "__VAULT_PATH__" not in init_content
    assert str(tmp_vault) in init_content
    assert "facultad" in init_content
    assert "Materia" in init_content  # rules content embedded


def test_install_writes_remember_command(tmp_path: Path, tmp_vault: Path):
    claude_home = tmp_path / ".claude"
    claude_home.mkdir()
    tx_log = TransactionLog(tmp_path / "tx.json")

    install_memory_loop(
        adapter_dir=FIXTURE,
        claude_home=claude_home,
        vault_path=tmp_vault,
        log=tx_log,
    )

    remember = claude_home / "commands" / "remember.md"
    assert remember.exists()
    content = remember.read_text()
    assert "apunte_clase" in content
    assert "apuntes/<materia>" in content


def test_install_records_rollback(tmp_path: Path, tmp_vault: Path):
    claude_home = tmp_path / ".claude"
    claude_home.mkdir()
    tx_log = TransactionLog(tmp_path / "tx.json")

    install_memory_loop(
        adapter_dir=FIXTURE,
        claude_home=claude_home,
        vault_path=tmp_vault,
        log=tx_log,
    )

    assert len(tx_log.entries()) >= 2  # at least init hook + stop hook

    tx_log.rollback()
    assert not (claude_home / "hooks" / "rufino-memory-loop-init.sh").exists()


def test_install_fails_on_invalid_manifest(tmp_path: Path, tmp_vault: Path):
    bad_dir = tmp_path / "bad-adapter"
    bad_dir.mkdir()
    (bad_dir / "manifest.yaml").write_text("vertical_name: x\n")
    tx_log = TransactionLog(tmp_path / "tx.json")

    with pytest.raises(InstallationError):
        install_memory_loop(
            adapter_dir=bad_dir,
            claude_home=tmp_path / ".claude",
            vault_path=tmp_vault,
            log=tx_log,
        )
