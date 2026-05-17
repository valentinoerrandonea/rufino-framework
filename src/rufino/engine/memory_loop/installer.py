from pathlib import Path

from rufino.engine.memory_loop.manifest import parse_manifest, ManifestParseError
from rufino.engine.memory_loop.validator import VerticalConfigValidator
from rufino.runtime.transaction_log import (
    TransactionLog,
    apply_and_log,
    register_rollback,
)


class InstallationError(Exception):
    """Raised when adapter installation cannot proceed."""


_HOOKS_PKG_DIR = Path(__file__).parent / "hooks"
_HEREDOC_MARKER = "RUFINO_RULES_EOF"


def _rmdir_if_empty(target: str) -> None:
    """Rollback for installer-created directories.

    Unlike the generic ``rmdir`` handler (which uses ``shutil.rmtree``),
    this leaves the directory in place if it has gained content from
    outside the installer's own log — preventing collateral damage to
    files an external tool may have dropped into ``~/.claude/hooks/``
    between install and rollback.
    """
    p = Path(target)
    if p.is_dir() and not any(p.iterdir()):
        p.rmdir()


register_rollback("rmdir_if_empty", _rmdir_if_empty)


def _hook_template(name: str) -> str:
    return (_HOOKS_PKG_DIR / name).read_text()


def _write_executable(target: Path, content: str) -> None:
    target.write_text(content)
    target.chmod(0o755)


def _read_rule(adapter_dir: Path, rule_rel: str) -> str:
    """Read a rule extension after checking it stays inside adapter_dir."""
    adapter_root = adapter_dir.resolve()
    rule_path = (adapter_dir / rule_rel).resolve()
    try:
        rule_path.relative_to(adapter_root)
    except ValueError:
        raise InstallationError(
            f"rule_extensions entry {rule_rel!r} escapes adapter_dir "
            f"(resolved to {rule_path})"
        )
    if not rule_path.exists():
        raise InstallationError(f"Rule extension not found: {rule_path}")
    return rule_path.read_text()


def install_memory_loop(
    *,
    adapter_dir: Path,
    claude_home: Path,
    vault_path: Path,
    log: TransactionLog,
) -> None:
    """Materialize a Memory loop adapter into the user's Claude home.

    Installs:
      - hooks/rufino-memory-loop-init.sh
      - hooks/rufino-memory-loop-stop.sh
      - commands/remember.md (parameterized with note_destinations)

    All operations are recorded in `log` so a rollback removes every artifact.
    """
    manifest_path = adapter_dir / "manifest.yaml"
    if not manifest_path.exists():
        raise InstallationError(f"No manifest.yaml in {adapter_dir}")

    try:
        manifest = parse_manifest(manifest_path.read_text())
    except ManifestParseError as e:
        raise InstallationError(f"Invalid manifest: {e}") from e

    validation = VerticalConfigValidator().validate({
        "adapter_name": manifest.adapter_name,
        "vertical_name": manifest.vertical_name,
        "entity_types": list(manifest.entity_types),
        "note_destinations": manifest.note_destinations,
        "rule_extensions": list(manifest.rule_extensions),
    })
    if not validation.ok:
        raise InstallationError(f"Validation failed:\n{validation.report()}")

    rules_concat = ""
    for rule_rel in manifest.rule_extensions:
        rules_concat += _read_rule(adapter_dir, rule_rel) + "\n\n"

    # Quoted heredoc would otherwise terminate early if a rule contains the
    # marker on a line by itself — and everything after would be parsed as bash.
    for line in rules_concat.splitlines():
        if line.strip() == _HEREDOC_MARKER:
            raise InstallationError(
                f"Rule content contains reserved heredoc marker "
                f"{_HEREDOC_MARKER!r} on a line by itself"
            )

    hooks_dir = claude_home / "hooks"
    commands_dir = claude_home / "commands"
    for d in (hooks_dir, commands_dir):
        if not d.exists():
            apply_and_log(
                log,
                op="mkdir",
                target=str(d),
                apply_fn=lambda d=d: d.mkdir(parents=True),
                rollback="rmdir_if_empty",
            )

    init_template = _hook_template("hook_init.sh")
    init_rendered = (
        init_template
        .replace("__VAULT_PATH__", str(vault_path))
        .replace("__VERTICAL_NAME__", manifest.vertical_name)
        .replace("__RULES_CONCAT__", rules_concat)
    )
    init_target = hooks_dir / "rufino-memory-loop-init.sh"
    apply_and_log(
        log,
        op="write",
        target=str(init_target),
        apply_fn=lambda: _write_executable(init_target, init_rendered),
        rollback="delete",
    )

    stop_target = hooks_dir / "rufino-memory-loop-stop.sh"
    apply_and_log(
        log,
        op="write",
        target=str(stop_target),
        apply_fn=lambda: _write_executable(stop_target, _hook_template("hook_stop.sh")),
        rollback="delete",
    )

    destinations_md = "\n".join(
        f"- `{entity}` → `{path}`" for entity, path in manifest.note_destinations.items()
    )
    remember_content = (
        f"# /remember (vertical: {manifest.vertical_name})\n\n"
        f"Cuando el user te pida guardar algo al vault, decidí el destino según el tipo:\n\n"
        f"{destinations_md}\n"
    )
    remember_target = commands_dir / "remember.md"
    apply_and_log(
        log,
        op="write",
        target=str(remember_target),
        apply_fn=lambda: remember_target.write_text(remember_content),
        rollback="delete",
    )
