from pathlib import Path
from click.testing import CliRunner
from rufino.cli import cli


FIXTURE = Path(__file__).parent / "fixtures" / "adapters" / "memory-loop-facultad"


def test_install_memory_loop_cli(tmp_path: Path, tmp_vault: Path):
    claude_home = tmp_path / ".claude"
    claude_home.mkdir()
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "install-memory-loop",
            str(FIXTURE),
            "--vault", str(tmp_vault),
            "--claude-home", str(claude_home),
        ],
    )

    assert result.exit_code == 0, result.output
    assert (claude_home / "hooks" / "rufino-memory-loop-init-vault.sh").exists()
    assert "installed" in result.output.lower()


def test_install_memory_loop_cli_fails_on_bad_manifest(tmp_path: Path, tmp_vault: Path):
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "manifest.yaml").write_text("vertical_name: x\n")
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "install-memory-loop", str(bad),
            "--vault", str(tmp_vault),
            "--claude-home", str(tmp_path / ".claude"),
        ],
    )
    assert result.exit_code != 0


def test_install_memory_loop_cli_rolls_back_on_mid_install_failure(
    tmp_path: Path, tmp_vault: Path
):
    """If install fails after some artifacts were written, the CLI must
    roll them back automatically — no orphaned hooks in ~/.claude/."""
    # Adapter that passes manifest validation but references a missing rule,
    # so the failure happens AFTER directories may have been created.
    adapter = tmp_path / "partial-adapter"
    adapter.mkdir()
    (adapter / "manifest.yaml").write_text(
        "adapter_name: partial\n"
        "vertical_name: x\n"
        "entity_types: [a]\n"
        "note_destinations:\n"
        "  a: x/<slug>.md\n"
        "rule_extensions:\n"
        "  - ./rules/missing.md\n"
    )
    claude_home = tmp_path / ".claude"
    claude_home.mkdir()
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "install-memory-loop", str(adapter),
            "--vault", str(tmp_vault),
            "--claude-home", str(claude_home),
        ],
    )

    assert result.exit_code != 0
    assert not (claude_home / "hooks" / "rufino-memory-loop-init-vault.sh").exists()


def test_install_memory_loop_cli_tx_log_keyed_by_vault_slug(tmp_path: Path):
    """Two installs from the same adapter_dir into different vaults must NOT
    share the tx log path — otherwise a rollback of the second install would
    destroy the audit trail of the first."""
    from rufino.runtime.vault_slug import compute_vault_slug

    claude_home = tmp_path / ".claude"
    claude_home.mkdir()
    vault_a = tmp_path / "vault-a"
    vault_a.mkdir()
    vault_b = tmp_path / "vault-b"
    vault_b.mkdir()
    runner = CliRunner()

    for vault in (vault_a, vault_b):
        result = runner.invoke(
            cli,
            [
                "install-memory-loop", str(FIXTURE),
                "--vault", str(vault),
                "--claude-home", str(claude_home),
            ],
        )
        assert result.exit_code == 0, result.output

    tx_dir = claude_home / "tx"
    assert (tx_dir / f"install-memory-loop-{compute_vault_slug(vault_a)}.json").exists()
    assert (tx_dir / f"install-memory-loop-{compute_vault_slug(vault_b)}.json").exists()
