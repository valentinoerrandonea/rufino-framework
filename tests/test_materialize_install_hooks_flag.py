"""Tests for the opt-in hook install flag + per-vault MCP server name.

Covers the materializer's `install_hooks` keyword and the CLI's
`--install-hooks/--no-install-hooks` flag, plus the requirement that the
MCP server entry registered in ~/.claude.json uses `ask-rufino-<slug>` so
two vaults can coexist there as well.
"""
import json
from pathlib import Path

from click.testing import CliRunner

from rufino.cli import cli
from rufino.runtime.vault_slug import compute_vault_slug
from rufino.wizard.materializer import materialize
from rufino.wizard.spec_schema import validate_spec


MINIMAL_SPEC = {
    "vertical_name": "facultad",
    "patterns": ["long_documents_extraction"],
    "entities": ["apunte_clase"],
    "sources": [],
    "processing": [],
    "outputs": [],
    "vocabulary": {"apunte_clase": "apuntes/<slug>.md"},
}


def test_materialize_default_does_not_install_hooks(tmp_path: Path):
    """Default is conservative: hooks are not installed unless requested."""
    from rufino.runtime.vault_slug import compute_vault_slug

    spec = validate_spec(MINIMAL_SPEC)
    vault = tmp_path / "study-2026"
    claude_home = tmp_path / ".claude"
    state_dir = tmp_path / ".state"

    result = materialize(
        spec=spec,
        vault_root=vault,
        claude_home=claude_home,
        state_dir=state_dir,
    )
    assert result.success, result.errors
    # Vault skeleton still gets built.
    assert (vault / "perfil.md").exists()
    # But the Claude home is untouched — no hooks dir, no commands dir.
    assert not (claude_home / "hooks").exists()
    assert not (claude_home / "commands").exists()
    # Adapter manifest IS written even when hooks are skipped — the user can
    # enable hooks later via `rufino install-memory-loop` without re-running
    # the wizard (this is the explicit promise of the install_hooks=False mode).
    slug = compute_vault_slug(vault)
    assert (state_dir.parent / "adapters" / "memory_loop" / slug / "manifest.yaml").exists()


def test_materialize_with_install_hooks_true_installs_them(tmp_path: Path):
    spec = validate_spec(MINIMAL_SPEC)
    vault = tmp_path / "study-2026"
    claude_home = tmp_path / ".claude"

    result = materialize(
        spec=spec,
        vault_root=vault,
        claude_home=claude_home,
        state_dir=tmp_path / ".state",
        install_hooks=True,
    )
    assert result.success, result.errors
    slug = compute_vault_slug(vault)
    assert (claude_home / "hooks" / f"rufino-memory-loop-init-{slug}.sh").exists()


def test_cli_materialize_no_install_hooks_skips_them(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", classmethod(lambda cls: tmp_path))

    spec_file = tmp_path / "spec.json"
    spec_file.write_text(json.dumps(MINIMAL_SPEC))

    res = CliRunner().invoke(cli, [
        "materialize",
        "--spec", str(spec_file),
        "--vault", str(tmp_path / "vault-x"),
        "--claude-home", str(tmp_path / ".claude_home"),
        "--state-dir", str(tmp_path / ".state"),
        "--no-install-hooks",
    ])
    assert res.exit_code == 0, res.output
    assert not (tmp_path / ".claude_home" / "hooks").exists()


def test_cli_materialize_install_hooks_installs_them(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", classmethod(lambda cls: tmp_path))

    spec_file = tmp_path / "spec.json"
    spec_file.write_text(json.dumps(MINIMAL_SPEC))

    vault = tmp_path / "vault-y"
    res = CliRunner().invoke(cli, [
        "materialize",
        "--spec", str(spec_file),
        "--vault", str(vault),
        "--claude-home", str(tmp_path / ".claude_home"),
        "--state-dir", str(tmp_path / ".state"),
        "--install-hooks",
    ])
    assert res.exit_code == 0, res.output
    slug = compute_vault_slug(vault)
    assert (
        tmp_path / ".claude_home" / "hooks" / f"rufino-memory-loop-init-{slug}.sh"
    ).exists()


def test_cli_materialize_registers_per_vault_mcp_server(tmp_path: Path, monkeypatch):
    """The MCP entry name must include the vault slug so a second materialize
    does NOT clobber the first vault's entry in ~/.claude.json."""
    monkeypatch.setattr("pathlib.Path.home", classmethod(lambda cls: tmp_path))

    spec_file = tmp_path / "spec.json"
    spec_file.write_text(json.dumps(MINIMAL_SPEC))

    vault = tmp_path / "study-2026"
    res = CliRunner().invoke(cli, [
        "materialize",
        "--spec", str(spec_file),
        "--vault", str(vault),
        "--claude-home", str(tmp_path / ".claude_home"),
        "--state-dir", str(tmp_path / ".state"),
    ])
    assert res.exit_code == 0, res.output

    cfg = json.loads((tmp_path / ".claude.json").read_text())
    slug = compute_vault_slug(vault)
    entry = cfg["mcpServers"][f"ask-rufino-{slug}"]
    assert entry["args"][:3] == ["mcp-server", "--vault", str(vault)]


def test_cli_two_materialize_calls_coexist_in_claude_json(tmp_path: Path, monkeypatch):
    """Two vaults materialized on the same machine each get their own MCP
    entry — neither overwrites the other."""
    monkeypatch.setattr("pathlib.Path.home", classmethod(lambda cls: tmp_path))

    spec_file = tmp_path / "spec.json"
    spec_file.write_text(json.dumps(MINIMAL_SPEC))

    vault_a = tmp_path / "vault-a"
    vault_b = tmp_path / "vault-b"
    for vault, state in ((vault_a, ".state-a"), (vault_b, ".state-b")):
        res = CliRunner().invoke(cli, [
            "materialize",
            "--spec", str(spec_file),
            "--vault", str(vault),
            "--claude-home", str(tmp_path / ".claude_home"),
            "--state-dir", str(tmp_path / state),
        ])
        assert res.exit_code == 0, res.output

    cfg = json.loads((tmp_path / ".claude.json").read_text())
    servers = cfg["mcpServers"]
    assert f"ask-rufino-{compute_vault_slug(vault_a)}" in servers
    assert f"ask-rufino-{compute_vault_slug(vault_b)}" in servers
