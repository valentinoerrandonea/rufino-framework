import subprocess
from pathlib import Path
from rufino.engine.memory_loop.installer import install_memory_loop
from rufino.runtime.transaction_log import TransactionLog


FIXTURE = Path(__file__).parent / "fixtures" / "adapters" / "memory-loop-facultad"


def test_installed_hooks_actually_execute(tmp_path: Path, tmp_vault: Path):
    (tmp_vault / "perfil.md").write_text("# Perfil\nVal estudia ML I.\n")
    (tmp_vault / "preferencias.md").write_text("# Preferencias\nEspañol argentino.\n")

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
    init_result = subprocess.run(
        ["bash", str(init_hook)], capture_output=True, text=True, check=True
    )
    # Stderr must be empty — placeholder leakage into comments/code would print
    # "command not found" errors here even when the script's overall exit is 0.
    assert init_result.stderr == "", init_result.stderr
    assert "Val estudia ML I" in init_result.stdout
    assert "facultad" in init_result.stdout
    assert "Materia" in init_result.stdout

    stop_hook = claude_home / "hooks" / "rufino-memory-loop-stop.sh"
    stop_result = subprocess.run(
        ["bash", str(stop_hook)], capture_output=True, text=True, check=True
    )
    assert stop_result.stderr == "", stop_result.stderr
    assert "MEMORY CHECK" in stop_result.stdout


def test_rollback_after_install_leaves_no_trace(tmp_path: Path, tmp_vault: Path):
    claude_home = tmp_path / ".claude"
    claude_home.mkdir()
    tx_log = TransactionLog(tmp_path / "tx.json")

    install_memory_loop(
        adapter_dir=FIXTURE,
        claude_home=claude_home,
        vault_path=tmp_vault,
        log=tx_log,
    )

    tx_log.rollback()

    assert not (claude_home / "hooks" / "rufino-memory-loop-init.sh").exists()
    assert not (claude_home / "hooks" / "rufino-memory-loop-stop.sh").exists()
    assert not (claude_home / "commands" / "remember.md").exists()
