"""Per-vault naming + multi-vault coexistence tests for install_memory_loop.

These tests pin down the behavior described in
docs/superpowers/specs/2026-05-18-multi-vault-support-design.md:
artifact filenames embed the vault slug, two distinct vaults coexist
in the same ~/.claude/, and re-installing the *same* vault still refuses.
"""
from pathlib import Path

import pytest

from rufino.engine.memory_loop.installer import (
    install_memory_loop,
    InstallationError,
)
from rufino.runtime.transaction_log import TransactionLog
from rufino.runtime.vault_slug import compute_vault_slug


FIXTURE = Path(__file__).parent / "fixtures" / "adapters" / "memory-loop-facultad"


def _install(adapter_dir: Path, claude_home: Path, vault: Path, tx_file: Path) -> None:
    tx_log = TransactionLog(tx_file)
    install_memory_loop(
        adapter_dir=adapter_dir,
        claude_home=claude_home,
        vault_path=vault,
        log=tx_log,
    )


def test_installed_filenames_include_vault_slug(tmp_path: Path):
    vault = tmp_path / "study-2026"
    vault.mkdir()
    claude_home = tmp_path / ".claude"
    claude_home.mkdir()

    _install(FIXTURE, claude_home, vault, tmp_path / "tx.json")

    slug = compute_vault_slug(vault)
    assert (claude_home / "hooks" / f"rufino-memory-loop-init-{slug}.sh").exists()
    assert (claude_home / "hooks" / f"rufino-memory-loop-stop-{slug}.sh").exists()
    assert (claude_home / "commands" / f"remember-{slug}.md").exists()


def test_two_distinct_vaults_coexist_in_same_claude_home(tmp_path: Path):
    """The main reason this work exists: installing two vaults must NOT collide."""
    claude_home = tmp_path / ".claude"
    claude_home.mkdir()

    vault_a = tmp_path / "vault-a"
    vault_a.mkdir()
    vault_b = tmp_path / "vault-b"
    vault_b.mkdir()

    _install(FIXTURE, claude_home, vault_a, tmp_path / "tx-a.json")
    # The second install must not raise — slugs differ.
    _install(FIXTURE, claude_home, vault_b, tmp_path / "tx-b.json")

    slug_a = compute_vault_slug(vault_a)
    slug_b = compute_vault_slug(vault_b)
    assert (claude_home / "hooks" / f"rufino-memory-loop-init-{slug_a}.sh").exists()
    assert (claude_home / "hooks" / f"rufino-memory-loop-init-{slug_b}.sh").exists()
    assert (claude_home / "commands" / f"remember-{slug_a}.md").exists()
    assert (claude_home / "commands" / f"remember-{slug_b}.md").exists()


def test_reinstalling_the_same_vault_still_refuses(tmp_path: Path):
    """Per-vault naming preserves the original safety check: installing the
    same vault twice would still cause a rollback to destroy the earlier
    install, so refuse it."""
    claude_home = tmp_path / ".claude"
    claude_home.mkdir()

    vault = tmp_path / "study"
    vault.mkdir()

    _install(FIXTURE, claude_home, vault, tmp_path / "tx-1.json")

    with pytest.raises(InstallationError, match="already installed"):
        _install(FIXTURE, claude_home, vault, tmp_path / "tx-2.json")


def test_init_hook_content_is_unchanged_by_per_vault_naming(tmp_path: Path):
    """Renaming files must not change what they do; the script body still
    substitutes vault path + vertical name + rules."""
    vault = tmp_path / "study-2026"
    vault.mkdir()
    claude_home = tmp_path / ".claude"
    claude_home.mkdir()

    _install(FIXTURE, claude_home, vault, tmp_path / "tx.json")

    slug = compute_vault_slug(vault)
    init = (claude_home / "hooks" / f"rufino-memory-loop-init-{slug}.sh").read_text()
    assert "__VAULT_PATH__" not in init
    assert str(vault) in init
    assert "facultad" in init
