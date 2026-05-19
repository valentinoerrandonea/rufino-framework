# Runtime internals

Los módulos en `src/rufino/runtime/` son el plumbing cross-cutting del framework: transaction log, sandbox, scheduler, secrets, validators, prereq checker, Claude config helpers.

Esto es **load-bearing infrastructure** — toda mutación al disco/keychain/launchd pasa por acá. Si vas a agregar un primitive nuevo o modificar materialización, leelos antes.

## Transaction log

**Archivo:** `src/rufino/runtime/transaction_log.py`
**API principal:** `TransactionLog`, `apply_and_log`, `register_rollback`

### Por qué existe

La materialización del bootstrap involucra muchas operaciones distintas: crear dirs en disco, escribir archivos, guardar secrets en Keychain, instalar plists en launchd. Si una falla a mitad, el cleanup parcial es **frágil con try/except** — fácil olvidarse uno, fácil que no sea idempotente.

El transaction log centraliza el problema: cada operación se declara con su inverso al mismo tiempo. Si todo OK → log se guarda como auditoría. Si falla → se lee en reverso, cada inverso se ejecuta.

### API

```python
from pathlib import Path
from rufino.runtime.transaction_log import TransactionLog, apply_and_log

# Crear un log nuevo (path donde se persiste el JSON)
tx_log = TransactionLog(Path("/tmp/install-tx.json"))

# Cada mutación pasa por apply_and_log:
apply_and_log(
    tx_log,
    op="mkdir",                                  # nombre del rollback handler
    target="/Users/beto/facultad",               # qué se está tocando
    apply_fn=lambda: Path("/Users/beto/facultad").mkdir(parents=True),
    rollback="rmdir_if_empty",                   # nombre del handler a usar para revert
)

# ... más operaciones ...

# Si algo falla en cualquier paso, llamá rollback() — corre los inversos en orden reverso
try:
    apply_and_log(tx_log, op="write", target=path, apply_fn=...)
except Exception:
    tx_log.rollback()
    raise
```

### Rollback handlers registrados

Hay un set built-in en `transaction_log.py`:

| Handler | Qué hace |
|---|---|
| `rmdir` | Borra dir (debe estar vacío) |
| `rmdir_if_empty` | Borra dir solo si está vacío — más seguro |
| `delete` | Borra archivo |
| `keychain_delete` | Borra entry del Keychain |
| `plist_uninstall` | `launchctl unload && rm` un plist |

### Registrar uno nuevo

Si agregás una mutación que no está cubierta:

```python
from rufino.runtime.transaction_log import register_rollback

def my_rollback(target: str) -> None:
    """Revert my custom operation."""
    # ... cleanup logic ...
    # IMPORTANTE: tiene que ser idempotente (no romper si ya está revertido)

register_rollback("my_op", my_rollback)
```

Después podés usarlo:

```python
apply_and_log(tx_log, op="my_op", target=x, apply_fn=..., rollback="my_op")
```

### Garantías

- **Atomic write del log JSON.** El log se escribe con `tmp + rename` para que el archivo siempre esté en estado válido — aún si el proceso muere durante el write.
- **Pre-execution logging.** El log se actualiza **antes** de ejecutar la op. Si el proceso muere durante la op, el rollback va a intentar revertir algo que quizás solo se aplicó a medias. Por eso los rollback handlers tienen que ser **idempotentes** (`rmdir_if_empty` no se queja si el dir no existe, `delete` no se queja si el archivo no está).
- **Rollback ordenado.** Las ops se revierten en orden reverso al de aplicación — last-in-first-out, igual que un undo stack.

### Tests

Cuando agregás una op nueva al framework, agregá un test que:

1. Crea un escenario donde la op se aplica a mitad de una secuencia
2. Fuerza un error después
3. Verifica que el rollback ejecuta limpio
4. Verifica que el estado del disco queda exactamente como pre-secuencia

Mirá `tests/test_transaction_log.py` para ejemplos.

---

## Sandbox (parcial)

**Archivo:** `src/rufino/runtime/sandbox.py`

### Estado

**Parcialmente implementado.** El framework planificó un sandbox `subprocess.run` para correr `transform.py` con timeout + env restringido + filesystem readonly + network bloqueado. v0.0.2 tiene la base de `subprocess` invocation con timeout, pero los hooks `transform_hook` no se invocan todavía (deferido — el manifest acepta el campo pero el runner no lo usa).

### API planificada

Cuando se implemente:

```python
from rufino.runtime.sandbox import run_in_sandbox

result = run_in_sandbox(
    script_path=adapter_dir / "transform.py",
    input_json={"key": "value"},
    timeout_seconds=60,           # default 60, max 300
    writes_to=adapter_dir / "output/",  # readonly excepto este path
    allow_network=False,          # default False
)
# result.stdout es el output JSON
# result.returncode = 0 si OK
```

### Restricciones planificadas

- **Filesystem:** readonly excepto `writes_to`.
- **Network:** bloqueado por default (DNS + connect patcheados); opt-in con `allow_network=True` (requiere log + user OK al install).
- **Stdin/stdout:** JSON in, JSON out. Sin acceso a TTY.
- **Resource limits (Unix):** `RLIMIT_AS 512 MB`, `RLIMIT_CPU 30s`.
- **Env:** `PATH=/usr/bin`, `PYTHONPATH=<framework_helpers_v1>`.
- **Errores:** timeout = falla del adapter; non-zero exit = error reportado en lenguaje claro.

### Validador integrado

Cuando el adapter se instala, el validador del manifest corre un **smoke test del hook con input dummy** en el sandbox. Si falla, bloquea install.

---

## Scheduler

**Archivo:** `src/rufino/runtime/scheduler.py`

Abstracción cross-platform del scheduling de tasks recurrentes:

- **macOS:** materializa el cron del manifest en un `LaunchDaemon` plist y lo registra con `launchctl`
- **Linux:** materializa en un user cron job o un `systemd` timer (preferencia configurable)

### API

```python
from rufino.runtime.scheduler import ScheduledJob, install_job, uninstall_job

job = ScheduledJob(
    name="com.rufino.process-apunte",
    schedule="*/30 * * * *",            # cron expression
    command=[rufino_bin, "ingest", str(adapter_dir), ...],
    working_dir=adapter_dir,
    stdout_log=log_dir / "out.log",
    stderr_log=log_dir / "err.log",
)

install_job(job, tx_log=tx_log)         # registra + rollback handler
# ... or ...
uninstall_job(job)                      # cleanup
```

### Cron expression validation

El framework valida la expression contra ranges válidos (`0-59 0-23 1-31 1-12 0-7`). Expression inválida bloquea install.

### Tests

Los tests de scheduler usan mocks de `launchctl` / `crontab` para no tocar el sistema real. Mirá `tests/test_scheduler.py`.

---

## Secrets

**Archivo:** `src/rufino/runtime/secrets.py`

Abstracción sobre el Keychain del sistema (`security` CLI en macOS, Secret Service via `keyring` en Linux).

### API

```python
from rufino.runtime.secrets import store_secret, fetch_secret, delete_secret

store_secret(
    service="rufino-belo-oauth",
    account="val",
    secret="oauth-token-here",
)

token = fetch_secret(service="rufino-belo-oauth", account="val")

delete_secret(service="rufino-belo-oauth", account="val")
```

### Comportamiento

- En macOS usa `security add/find/delete-generic-password` via subprocess.
- En Linux usa la lib `keyring` (Secret Service / SecretStorage).
- Si el Keychain no está disponible (CI, container sin display), tira `KeyringNotAvailableError`. Los tests que dependen de Keychain marcan `pytest.skip` si está pasando — por eso ves `1 skipped` en suites locales sin Keychain.
- **`fetch_secret` nunca loggea el valor.** Si la op falla, el error menciona el service+account pero **no** el secret.

### Integración con tx log

Cuando un Ingest adapter declara `auth.type: oauth2`, el wizard registra el grant en el Keychain dentro del tx log:

```python
apply_and_log(
    tx_log,
    op="keychain_add",
    target=f"{service}:{account}",
    apply_fn=lambda: store_secret(service, account, token),
    rollback="keychain_delete",
)
```

Rollback de bootstrap → el secret se borra. **Pero el grant del lado del proveedor (Google, GitHub, etc.) NO se revoca** — eso requiere visitar la página del proveedor. El usuario tiene que ser informado.

---

## Validators

**Archivo:** `src/rufino/runtime/validator_base.py`

Protocolo + base class para validators de manifest. Cada engine implementa el suyo:

- `engine/ingest/manifest.py:IngestManifestValidator`
- `engine/process/manifest.py:ProcessManifestValidator`
- `engine/output/manifest.py:OutputManifestValidator`
- `engine/memory_loop/manifest.py:VerticalConfigValidator`
- `engine/qa/template.py:QuestionTemplateValidator`

### Protocolo

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class Validator(Protocol):
    def validate(self, manifest: dict) -> ValidationResult: ...
```

### ValidationResult

```python
@dataclass(frozen=True)
class ValidationResult:
    errors: tuple[str, ...]    # bloquean install
    warnings: tuple[str, ...]  # log pero no bloquean
```

### Reglas comunes (implementadas en `validator_base.py`)

- **Schema YAML válido.**
- **Required fields presentes.**
- **Triple vocabulary no usa keywords reservados** (`type`, `id`, `created`, `updated`, `tags`).
- **Tag axes sin overlap.**
- **Paths absolutos prohibidos.** Cualquier path en `destination`, `destination_path`, `template`, `path` (delivery) — resolved path **debe** estar dentro del vault o del adapter dir.
- **Referencias cruzadas válidas.** `process_with: <name>` exige que ese Process adapter exista.
- **Hook validation** (cuando se implemente el sandbox): smoke test con input dummy.

### Sumar reglas a un validator existente

```python
class MyEngineValidator(ValidatorBase):
    def validate(self, manifest: dict) -> ValidationResult:
        errors, warnings = [], []
        # ... reglas custom ...
        return ValidationResult(errors=tuple(errors), warnings=tuple(warnings))
```

### Tests

Cada validator tiene su test suite mirroring (`tests/test_ingest_manifest.py`, etc.). Pattern: tabla de casos malos (cada uno con su error message esperado) + casos buenos (no errores).

---

## Prereq checker

**Archivo:** `src/rufino/runtime/prereq_checker.py`

Cataloga pre-requisitos del sistema que el framework puede chequear antes de proponer una feature.

### API

```python
from rufino.runtime.prereq_checker import check_prereq, BUILT_IN_CHECKS

result = check_prereq("ollama")
# result.satisfied: bool
# result.message: str describing what was checked / what's missing
```

### Built-in checks

```python
BUILT_IN_CHECKS = {
    "ollama":     {"type": "command", "command": "ollama"},
    "security":   {"type": "command", "command": "security"},
    "node":       {"type": "command", "command": "node"},
    "python311":  {"type": "python_min_version", "version": (3, 11)},
    "gh":         {"type": "command", "command": "gh"},
    "rg":         {"type": "command", "command": "rg"},
}
```

### Uso desde el wizard

Antes de proponer una feature opcional, el wizard chequea sus prereqs:

```python
embeddings_check = check_prereq("ollama")
if not embeddings_check.satisfied:
    # Le pregunta al user si quiere instalar / saltear / activar después
```

El catálogo de qué features dependen de qué prereqs vive en `src/rufino/wizard/feature_prereqs.py` (cuando se materialice — actualmente embebido en el system prompt).

---

## Claude config helpers

**Archivo:** `src/rufino/runtime/claude_config.py`

Helpers para editar `~/.claude.json` de forma segura — concretamente para registrar/desregistrar MCP servers.

### API

```python
from rufino.runtime.claude_config import register_mcp_server

from rufino.runtime.vault_slug import compute_vault_slug

vault = Path("/Users/beto/facultad")
register_mcp_server(
    claude_config_path=Path.home() / ".claude.json",
    server_name=f"ask-rufino-{compute_vault_slug(vault)}",  # one entry per vault
    command="/usr/local/bin/rufino",
    args=["mcp-server", "--vault", str(vault)],
)
```

### Garantías

- **Atomic write** (`tmp + rename`).
- **Idempotente.** Si el server ya está registrado con los mismos args, no-op. Si está con args distintos, los actualiza.
- **Preserva el resto del JSON.** No reescribe campos que no son `mcpServers["<name>"]`.

---

## Cómo encaja todo

Un boostrap típico, de alto nivel:

```
1. rufino bootstrap
       ↓
2. wizard.system_prompt_assembler.build_system_prompt()
       ↓
3. subprocess.run(["claude", "-p", prompt, "--allowedTools", ...])
       ↓ (Claude conduce la entrevista)
4. Claude invoca: rufino materialize --spec /tmp/spec.json ...
       ↓
5. wizard.spec_schema.validate_spec(json)
       ↓ (SpecError → exit 1)
6. wizard.materializer.materialize(spec, vault, ...)
       ↓
       ├─→ apply_and_log(tx_log, "mkdir", vault, ...)
       ├─→ apply_and_log(tx_log, "write", perfil_md, ...)
       ├─→ engine.memory_loop.installer.install_memory_loop(...)
       │      └─→ apply_and_log(tx_log, "mkdir", ~/.claude/rules, ...)
       │      └─→ apply_and_log(tx_log, "write", rules.md, ...)
       ├─→ ... más adapters ...
       │
       └─→ Si OK: el log se persiste como auditoría
           Si error en cualquier paso: tx_log.rollback() (LIFO de inversos)
       ↓
7. claude_config.register_mcp_server(...)
       ↓
8. exit 0
```

Cualquier error en pasos 4-7 → rollback completo → el disco queda como pre-bootstrap → exit 2.

Esto es lo que sostiene la garantía de "big bang" del framework.
