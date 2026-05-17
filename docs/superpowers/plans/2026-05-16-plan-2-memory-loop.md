# Plan 2 — Memory loop primitive Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementar la primitive Memory loop: el shape "vertical config" del adapter (manifest + rules markdown), el validador del shape, los hooks `init` y `stop` para Claude Code, y el skill `/remember` parametrizable. Al final, un user puede instalar un adapter de Memory loop para un vertical (ej: facultad) y ver que Claude carga contexto del vertical al iniciar conversación y pregunta si guardar al cerrar.

**Architecture:** El Memory loop NO ejecuta scripts ni LLM. Es **configuración**: un manifest YAML que declara entity types + destinos de notas + reglas markdown que Claude Code lee como instrucciones. La primitive del framework provee: parser del manifest, validador del shape, scripts de hook (`hook_init.sh`, `hook_stop.sh`) que Claude Code dispara automáticamente, y un comando CLI `rufino install-memory-loop <adapter_dir>` que materializa la instalación en `~/.claude/`.

**Tech Stack:** Python 3.11+ (validador, parser, installer), bash (hooks que Claude Code consume), markdown (rules), YAML (manifest).

**Dependencias previas:** Plan 1 (Foundation) — usa `Validator`, `ValidationResult`, CLI base.

**Plans que dependen de este:** Plan 7 (Query layer — el hook init invoca Query para chequear vault), Plan 8 (Wizard — el wizard genera adapters de Memory loop).

---

## File Structure

```
src/rufino/engine/memory_loop/
├── __init__.py
├── manifest.py                # MemoryLoopManifest dataclass + parser YAML
├── validator.py               # VerticalConfigValidator (extends Validator)
├── installer.py               # install_memory_loop(adapter_dir) → side effects en ~/.claude/
└── hooks/
    ├── hook_init.sh           # template del hook init (Bash)
    └── hook_stop.sh           # template del hook stop (Bash)
src/rufino/cli.py              # MODIFY: agregar `rufino install-memory-loop <path>`
tests/test_memory_loop_manifest.py
tests/test_memory_loop_validator.py
tests/test_memory_loop_installer.py
tests/fixtures/adapters/memory-loop-facultad/
├── manifest.yaml
└── rules/
    ├── facultad-vocabulary.md
    └── facultad-conventions.md
```

**File responsibilities:**

| File | Responsibility |
|---|---|
| `manifest.py` | Dataclass `MemoryLoopManifest` + función `parse_manifest(yaml_text) → MemoryLoopManifest` |
| `validator.py` | `VerticalConfigValidator` que implementa `Validator` (Plan 1) y chequea los campos del manifest |
| `installer.py` | Función `install_memory_loop(adapter_dir, claude_home, log)` que copia rules, instala hooks parametrizados, escribe `~/.claude/commands/remember.md` con `note_destinations` sustituidos |
| `hook_init.sh` | Script bash con placeholders que se sustituyen al instalar. Output va a Claude Code como context. |
| `hook_stop.sh` | Script bash que printa el prompt de "guardar al cerrar". |
| `cli.py` | Comando nuevo `rufino install-memory-loop <adapter_dir>` |

---

## Task 1: Manifest dataclass + YAML parser

**Files:**
- Create: `src/rufino/engine/__init__.py`
- Create: `src/rufino/engine/memory_loop/__init__.py`
- Create: `src/rufino/engine/memory_loop/manifest.py`
- Create: `tests/test_memory_loop_manifest.py`

- [ ] **Step 1: Write the failing test**

`tests/test_memory_loop_manifest.py`:
```python
import pytest
from rufino.engine.memory_loop.manifest import (
    MemoryLoopManifest,
    parse_manifest,
    ManifestParseError,
)


VALID_YAML = """
adapter_name: memory-loop-facultad
vertical_name: facultad

entity_types: [apunte_clase, materia, profesor, paper, tp, examen]

note_destinations:
  apunte_clase: "apuntes/<materia>/<YYYY-MM-DD>-<slug>.md"
  paper: "papers/<materia>/<slug>.md"

rule_extensions:
  - ./rules/facultad-vocabulary.md
  - ./rules/facultad-conventions.md
"""


def test_parses_full_manifest():
    m = parse_manifest(VALID_YAML)
    assert m.adapter_name == "memory-loop-facultad"
    assert m.vertical_name == "facultad"
    assert "apunte_clase" in m.entity_types
    assert m.note_destinations["paper"] == "papers/<materia>/<slug>.md"
    assert m.rule_extensions == [
        "./rules/facultad-vocabulary.md",
        "./rules/facultad-conventions.md",
    ]


def test_missing_required_field_raises():
    yaml = "vertical_name: facultad\n"
    with pytest.raises(ManifestParseError, match="adapter_name"):
        parse_manifest(yaml)


def test_empty_entity_types_raises():
    yaml = """
adapter_name: x
vertical_name: y
entity_types: []
note_destinations: {}
"""
    with pytest.raises(ManifestParseError, match="entity_types"):
        parse_manifest(yaml)


def test_destinations_must_be_relative_paths():
    yaml = """
adapter_name: x
vertical_name: y
entity_types: [a]
note_destinations:
  a: "/absolute/path.md"
"""
    with pytest.raises(ManifestParseError, match="absolute path"):
        parse_manifest(yaml)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_memory_loop_manifest.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the manifest module**

`src/rufino/engine/__init__.py`:
```python
```

`src/rufino/engine/memory_loop/__init__.py`:
```python
from rufino.engine.memory_loop.manifest import MemoryLoopManifest, parse_manifest

__all__ = ["MemoryLoopManifest", "parse_manifest"]
```

`src/rufino/engine/memory_loop/manifest.py`:
```python
from dataclasses import dataclass
from pathlib import PurePath
import yaml


class ManifestParseError(Exception):
    """Raised when manifest YAML is invalid or missing required fields."""


@dataclass(frozen=True)
class MemoryLoopManifest:
    adapter_name: str
    vertical_name: str
    entity_types: tuple[str, ...]
    note_destinations: dict[str, str]
    rule_extensions: tuple[str, ...]


_REQUIRED_FIELDS = ("adapter_name", "vertical_name", "entity_types", "note_destinations")


def parse_manifest(yaml_text: str) -> MemoryLoopManifest:
    try:
        raw = yaml.safe_load(yaml_text)
    except yaml.YAMLError as e:
        raise ManifestParseError(f"Invalid YAML: {e}") from e

    if not isinstance(raw, dict):
        raise ManifestParseError("Manifest root must be a mapping")

    missing = [f for f in _REQUIRED_FIELDS if f not in raw]
    if missing:
        raise ManifestParseError(f"Missing required fields: {missing}")

    entity_types = raw["entity_types"]
    if not isinstance(entity_types, list) or len(entity_types) == 0:
        raise ManifestParseError("entity_types must be a non-empty list")

    destinations = raw["note_destinations"]
    if not isinstance(destinations, dict):
        raise ManifestParseError("note_destinations must be a mapping")

    for entity, path in destinations.items():
        if PurePath(path).is_absolute():
            raise ManifestParseError(
                f"note_destinations[{entity!r}] must be relative, got absolute path {path!r}"
            )

    return MemoryLoopManifest(
        adapter_name=raw["adapter_name"],
        vertical_name=raw["vertical_name"],
        entity_types=tuple(entity_types),
        note_destinations=dict(destinations),
        rule_extensions=tuple(raw.get("rule_extensions", [])),
    )
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_memory_loop_manifest.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/rufino/engine/ tests/test_memory_loop_manifest.py
git commit -m "feat(memory-loop): manifest dataclass + YAML parser with validation"
```

---

## Task 2: Vertical config validator

**Files:**
- Create: `src/rufino/engine/memory_loop/validator.py`
- Create: `tests/test_memory_loop_validator.py`

- [ ] **Step 1: Write the failing test**

`tests/test_memory_loop_validator.py`:
```python
import pytest
from rufino.engine.memory_loop.validator import VerticalConfigValidator
from rufino.runtime.validator_base import Validator


def test_validator_implements_protocol():
    v = VerticalConfigValidator()
    assert isinstance(v, Validator)


def test_valid_manifest_yields_no_errors():
    v = VerticalConfigValidator()
    manifest = {
        "adapter_name": "ok",
        "vertical_name": "facultad",
        "entity_types": ["a", "b"],
        "note_destinations": {"a": "x/<slug>.md", "b": "y/<slug>.md"},
        "rule_extensions": ["./r.md"],
    }
    result = v.validate(manifest)
    assert result.ok
    assert result.errors == []


def test_destination_referencing_undeclared_entity_warns():
    v = VerticalConfigValidator()
    manifest = {
        "adapter_name": "ok",
        "vertical_name": "x",
        "entity_types": ["a"],
        "note_destinations": {"a": "p/<slug>.md", "ghost": "q/<slug>.md"},
        "rule_extensions": [],
    }
    result = v.validate(manifest)
    assert result.ok  # warnings don't block
    assert any("ghost" in w.message for w in result.warnings)


def test_entity_without_destination_warns():
    v = VerticalConfigValidator()
    manifest = {
        "adapter_name": "ok",
        "vertical_name": "x",
        "entity_types": ["a", "b"],
        "note_destinations": {"a": "p/<slug>.md"},
        "rule_extensions": [],
    }
    result = v.validate(manifest)
    assert result.ok
    assert any("b" in w.message for w in result.warnings)


def test_adapter_name_must_be_kebab_case():
    v = VerticalConfigValidator()
    manifest = {
        "adapter_name": "Bad Name",
        "vertical_name": "x",
        "entity_types": ["a"],
        "note_destinations": {"a": "p/<slug>.md"},
        "rule_extensions": [],
    }
    result = v.validate(manifest)
    assert not result.ok
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_memory_loop_validator.py -v`
Expected: FAIL

- [ ] **Step 3: Write the validator**

`src/rufino/engine/memory_loop/validator.py`:
```python
import re
from typing import Any
from rufino.runtime.validator_base import (
    ValidationResult, ValidationError, ValidationWarning,
)


_KEBAB_RE = re.compile(r"^[a-z][a-z0-9-]*$")


class VerticalConfigValidator:
    """Validates manifests for Memory loop adapters (vertical config shape)."""

    def validate(self, manifest: dict[str, Any]) -> ValidationResult:
        result = ValidationResult()

        name = manifest.get("adapter_name", "")
        if not _KEBAB_RE.match(name):
            result.errors.append(ValidationError(
                field="adapter_name",
                message=f"must be kebab-case (lowercase, hyphens), got {name!r}",
            ))

        entities = set(manifest.get("entity_types", []))
        destinations = manifest.get("note_destinations", {})

        # Warning: destination references an undeclared entity
        for entity in destinations:
            if entity not in entities:
                result.warnings.append(ValidationWarning(
                    field="note_destinations",
                    message=f"references entity {entity!r} not declared in entity_types",
                ))

        # Warning: entity without destination
        for entity in entities:
            if entity not in destinations:
                result.warnings.append(ValidationWarning(
                    field="entity_types",
                    message=f"entity {entity!r} has no entry in note_destinations",
                ))

        return result
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_memory_loop_validator.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/rufino/engine/memory_loop/validator.py tests/test_memory_loop_validator.py
git commit -m "feat(memory-loop): VerticalConfigValidator with errors + warnings"
```

---

## Task 3: Hook scripts (templates)

**Files:**
- Create: `src/rufino/engine/memory_loop/hooks/hook_init.sh`
- Create: `src/rufino/engine/memory_loop/hooks/hook_stop.sh`

- [ ] **Step 1: Write hook_init.sh template**

`src/rufino/engine/memory_loop/hooks/hook_init.sh`:
```bash
#!/usr/bin/env bash
# Rufino Memory loop — init hook
# Substituted at install time:
#   __VAULT_PATH__       — absolute path to user's vault
#   __VERTICAL_NAME__    — name of the vertical (e.g. "facultad")
#   __RULES_CONCAT__     — content of all rule_extensions concatenated

set -euo pipefail

VAULT="__VAULT_PATH__"

echo "## Vault: __VERTICAL_NAME__"
echo
echo "### perfil.md"
[ -f "$VAULT/perfil.md" ] && cat "$VAULT/perfil.md" || echo "(perfil not initialized)"
echo
echo "### preferencias.md"
[ -f "$VAULT/preferencias.md" ] && cat "$VAULT/preferencias.md" || echo "(preferences not initialized)"
echo
echo "### Reglas del vertical"
cat <<'RUFINO_RULES_EOF'
__RULES_CONCAT__
RUFINO_RULES_EOF
```

- [ ] **Step 2: Write hook_stop.sh template**

`src/rufino/engine/memory_loop/hooks/hook_stop.sh`:
```bash
#!/usr/bin/env bash
# Rufino Memory loop — stop hook
# Output goes to Claude Code as feedback before closing the session.

echo "MEMORY CHECK: revisá si hay algo para guardar en el vault antes de cerrar."
```

- [ ] **Step 3: Verify both files are valid bash**

Run:
```bash
bash -n src/rufino/engine/memory_loop/hooks/hook_init.sh
bash -n src/rufino/engine/memory_loop/hooks/hook_stop.sh
echo "syntax OK"
```

Expected: `syntax OK`

- [ ] **Step 4: Commit**

```bash
git add src/rufino/engine/memory_loop/hooks/
git commit -m "feat(memory-loop): hook templates for init + stop"
```

---

## Task 4: Installer that materializes an adapter into ~/.claude/

**Files:**
- Create: `src/rufino/engine/memory_loop/installer.py`
- Create: `tests/fixtures/adapters/memory-loop-facultad/manifest.yaml`
- Create: `tests/fixtures/adapters/memory-loop-facultad/rules/facultad-vocabulary.md`
- Create: `tests/fixtures/adapters/memory-loop-facultad/rules/facultad-conventions.md`
- Create: `tests/test_memory_loop_installer.py`

- [ ] **Step 1: Create fixture adapter**

`tests/fixtures/adapters/memory-loop-facultad/manifest.yaml`:
```yaml
adapter_name: memory-loop-facultad
vertical_name: facultad

entity_types: [apunte_clase, materia, profesor]

note_destinations:
  apunte_clase: "apuntes/<materia>/<YYYY-MM-DD>-<slug>.md"
  materia: "materias/<slug>.md"
  profesor: "profesores/<slug>.md"

rule_extensions:
  - ./rules/facultad-vocabulary.md
  - ./rules/facultad-conventions.md
```

`tests/fixtures/adapters/memory-loop-facultad/rules/facultad-vocabulary.md`:
```markdown
# Vocabulario del vault facultad

Este vault registra apuntes, papers, profesores y materias.

## Entidades
- **Materia**: una asignatura del cursado.
- **Apunte de clase**: notas de una clase específica de una materia.
- **Profesor**: docente de una o más materias.
```

`tests/fixtures/adapters/memory-loop-facultad/rules/facultad-conventions.md`:
```markdown
# Convenciones del vault facultad

- Si el user menciona "anoté X en la clase de Y" → crear apunte_clase.
- Si el user menciona a un profe nuevo → crear profesor.
```

- [ ] **Step 2: Write the failing test**

`tests/test_memory_loop_installer.py`:
```python
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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_memory_loop_installer.py -v`
Expected: FAIL

- [ ] **Step 4: Write the installer**

`src/rufino/engine/memory_loop/installer.py`:
```python
from pathlib import Path
import importlib.resources as ilr

from rufino.engine.memory_loop.manifest import parse_manifest, ManifestParseError
from rufino.engine.memory_loop.validator import VerticalConfigValidator
from rufino.runtime.transaction_log import (
    TransactionLog, LogEntry, apply_and_log, register_rollback,
)


class InstallationError(Exception):
    """Raised when adapter installation cannot proceed."""


def _hook_template(name: str) -> str:
    # Located inside the rufino.engine.memory_loop.hooks package
    return (Path(__file__).parent / "hooks" / name).read_text()


def install_memory_loop(
    *,
    adapter_dir: Path,
    claude_home: Path,
    vault_path: Path,
    log: TransactionLog,
) -> None:
    """Materialize a Memory loop adapter into ~/.claude/.

    Installs: hooks/rufino-memory-loop-init.sh, hooks/rufino-memory-loop-stop.sh,
              commands/remember.md (parameterized with note_destinations).

    All operations are recorded in `log` for transactional rollback.
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

    # Concatenate rule extensions
    rules_concat = ""
    for rule_rel in manifest.rule_extensions:
        rule_path = (adapter_dir / rule_rel).resolve()
        if not rule_path.exists():
            raise InstallationError(f"Rule extension not found: {rule_path}")
        rules_concat += rule_path.read_text() + "\n\n"

    # Render init hook
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
        apply_fn=lambda: (init_target.write_text(init_rendered), init_target.chmod(0o755)),
        rollback="delete",
    )

    # Render stop hook (no substitutions needed)
    stop_target = hooks_dir / "rufino-memory-loop-stop.sh"
    apply_and_log(
        log,
        op="write",
        target=str(stop_target),
        apply_fn=lambda: (stop_target.write_text(_hook_template("hook_stop.sh")), stop_target.chmod(0o755)),
        rollback="delete",
    )

    # Render /remember command
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
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_memory_loop_installer.py -v`
Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
git add src/rufino/engine/memory_loop/installer.py tests/fixtures/adapters/memory-loop-facultad/ tests/test_memory_loop_installer.py
git commit -m "feat(memory-loop): installer that materializes adapters into ~/.claude/"
```

---

## Task 5: CLI command `rufino install-memory-loop <adapter_dir>`

**Files:**
- Modify: `src/rufino/cli.py`
- Create: `tests/test_cli_install_memory_loop.py`

- [ ] **Step 1: Write the failing test**

`tests/test_cli_install_memory_loop.py`:
```python
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
    assert (claude_home / "hooks" / "rufino-memory-loop-init.sh").exists()
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli_install_memory_loop.py -v`
Expected: FAIL with `No such command 'install-memory-loop'`

- [ ] **Step 3: Add command to CLI**

Append to `src/rufino/cli.py`:
```python
from pathlib import Path
from rufino.engine.memory_loop.installer import install_memory_loop, InstallationError
from rufino.runtime.transaction_log import TransactionLog


@cli.command(name="install-memory-loop")
@click.argument("adapter_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--vault", "vault_path", required=True, type=click.Path(path_type=Path),
              help="Path to the user's vault root")
@click.option("--claude-home", "claude_home", required=True, type=click.Path(path_type=Path),
              help="Path to user's ~/.claude/ directory")
def install_memory_loop_cmd(adapter_dir: Path, vault_path: Path, claude_home: Path) -> None:
    """Install a Memory loop adapter into ~/.claude/."""
    tx_path = claude_home / "tx" / f"install-memory-loop-{adapter_dir.name}.json"
    tx_path.parent.mkdir(parents=True, exist_ok=True)
    tx_log = TransactionLog(tx_path)
    try:
        install_memory_loop(
            adapter_dir=adapter_dir,
            claude_home=claude_home,
            vault_path=vault_path,
            log=tx_log,
        )
    except InstallationError as e:
        click.echo(f"Error: {e}", err=True)
        raise click.exceptions.Exit(code=1)
    click.echo(f"Adapter '{adapter_dir.name}' installed to {claude_home}")
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_cli_install_memory_loop.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/rufino/cli.py tests/test_cli_install_memory_loop.py
git commit -m "feat(memory-loop): CLI command install-memory-loop"
```

---

## Task 6: End-to-end smoke test (install + hooks runnable)

**Files:**
- Create: `tests/test_memory_loop_smoke.py`

- [ ] **Step 1: Write the smoke test**

`tests/test_memory_loop_smoke.py`:
```python
import subprocess
from pathlib import Path
from rufino.engine.memory_loop.installer import install_memory_loop
from rufino.runtime.transaction_log import TransactionLog


FIXTURE = Path(__file__).parent / "fixtures" / "adapters" / "memory-loop-facultad"


def test_installed_hooks_actually_execute(tmp_path: Path, tmp_vault: Path):
    # Seed minimal perfil + preferencias in vault
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
    init_output = subprocess.check_output(["bash", str(init_hook)], text=True)
    assert "Val estudia ML I" in init_output
    assert "facultad" in init_output
    assert "Materia" in init_output

    stop_hook = claude_home / "hooks" / "rufino-memory-loop-stop.sh"
    stop_output = subprocess.check_output(["bash", str(stop_hook)], text=True)
    assert "MEMORY CHECK" in stop_output


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
```

- [ ] **Step 2: Run the smoke test**

Run: `pytest tests/test_memory_loop_smoke.py -v`
Expected: 2 passed

- [ ] **Step 3: Run full suite**

Run: `pytest -v`
Expected: all tests pass (no regression).

- [ ] **Step 4: Commit**

```bash
git add tests/test_memory_loop_smoke.py
git commit -m "test(memory-loop): end-to-end smoke (install → hooks runnable → rollback clean)"
```

---

## Self-review checklist

- [ ] Manifest parser rejects all 4 invalid cases tested
- [ ] Installer is transactional: rollback removes ALL artifacts
- [ ] Hook templates have placeholders fully substituted at install
- [ ] CLI returns non-zero exit on InstallationError
- [ ] No literal string `__VAULT_PATH__` remains in installed hooks (regression check)
- [ ] `/remember` template lists all `note_destinations` declared

## Done criteria

- `pytest tests/test_memory_loop_*.py -v` reports all pass
- After install + rollback, `~/.claude/hooks/` and `~/.claude/commands/` have no rufino-memory-loop residue
- `./cli/rufino install-memory-loop <fixture> --vault X --claude-home Y` exits 0
