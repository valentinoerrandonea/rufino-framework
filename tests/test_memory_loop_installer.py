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


def test_install_rejects_rule_extension_path_traversal(tmp_path: Path, tmp_vault: Path):
    """A rule_extensions entry that escapes adapter_dir must be rejected."""
    adapter = tmp_path / "evil-adapter"
    adapter.mkdir()
    (adapter / "manifest.yaml").write_text(
        "adapter_name: evil\n"
        "vertical_name: evil\n"
        "entity_types: [a]\n"
        "note_destinations:\n"
        "  a: x/<slug>.md\n"
        "rule_extensions:\n"
        "  - ../../../../etc/hosts\n"
    )
    tx_log = TransactionLog(tmp_path / "tx.json")

    with pytest.raises(InstallationError, match="escapes adapter_dir"):
        install_memory_loop(
            adapter_dir=adapter,
            claude_home=tmp_path / ".claude",
            vault_path=tmp_vault,
            log=tx_log,
        )


def test_install_rejects_rule_containing_heredoc_marker(tmp_path: Path, tmp_vault: Path):
    """A rule whose content has the heredoc marker alone on a line would
    close the heredoc early and turn the rest into bash code."""
    adapter = tmp_path / "bad-marker-adapter"
    (adapter / "rules").mkdir(parents=True)
    (adapter / "manifest.yaml").write_text(
        "adapter_name: bad-marker\n"
        "vertical_name: x\n"
        "entity_types: [a]\n"
        "note_destinations:\n"
        "  a: x/<slug>.md\n"
        "rule_extensions:\n"
        "  - ./rules/oops.md\n"
    )
    (adapter / "rules" / "oops.md").write_text(
        "Some rule.\n"
        "RUFINO_RULES_EOF\n"
        "rm -rf /\n"
    )
    tx_log = TransactionLog(tmp_path / "tx.json")

    with pytest.raises(InstallationError, match="heredoc marker"):
        install_memory_loop(
            adapter_dir=adapter,
            claude_home=tmp_path / ".claude",
            vault_path=tmp_vault,
            log=tx_log,
        )


def test_mkdir_rollback_preserves_external_content(tmp_path: Path, tmp_vault: Path):
    """If something external lands inside an installer-created directory
    between install and rollback, the rollback must NOT wipe it out."""
    claude_home = tmp_path / ".claude"
    claude_home.mkdir()
    tx_log = TransactionLog(tmp_path / "tx.json")

    install_memory_loop(
        adapter_dir=FIXTURE,
        claude_home=claude_home,
        vault_path=tmp_vault,
        log=tx_log,
    )

    foreign = claude_home / "hooks" / "foreign-tool-hook.sh"
    foreign.write_text("# not ours\n")

    tx_log.rollback()

    assert not (claude_home / "hooks" / "rufino-memory-loop-init.sh").exists()
    assert foreign.exists(), "rollback wiped a file the installer did not create"
