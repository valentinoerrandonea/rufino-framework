from pathlib import Path

from rufino.engine.memory_loop.manifest import parse_manifest, ManifestParseError
from rufino.engine.memory_loop.validator import VerticalConfigValidator
from rufino.runtime.transaction_log import TransactionLog, apply_and_log


class InstallationError(Exception):
    """Raised when adapter installation cannot proceed."""


_HOOKS_PKG_DIR = Path(__file__).parent / "hooks"


def _hook_template(name: str) -> str:
    return (_HOOKS_PKG_DIR / name).read_text()


def _write_executable(target: Path, content: str) -> None:
    target.write_text(content)
    target.chmod(0o755)


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

    hooks_dir = claude_home / "hooks"
    commands_dir = claude_home / "commands"
    for d in (hooks_dir, commands_dir):
        if not d.exists():
            apply_and_log(
                log,
                op="mkdir",
                target=str(d),
                apply_fn=lambda d=d: d.mkdir(parents=True),
                rollback="rmdir",
            )

    rules_concat = ""
    for rule_rel in manifest.rule_extensions:
        rule_path = (adapter_dir / rule_rel).resolve()
        if not rule_path.exists():
            raise InstallationError(f"Rule extension not found: {rule_path}")
        rules_concat += rule_path.read_text() + "\n\n"

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
