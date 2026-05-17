# Plan 9 — Installer + Distribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Empaquetar todo lo construido en plans 1-8 para distribución: `install.sh` que pone `rufino` en `$PATH` + setup mínimo de directorios, `upgrade.sh` idempotente con migraciones secuenciales + backup, documentación por shape de adapter (4 docs) y por primitive (6 docs), README de quick start.

**Architecture:** Scripts bash POSIX simples. `install.sh` detecta SO, instala dependencias Python (pip), crea `~/.rufino/` con subdirs estándar, agrega `rufino` al PATH (via shell rc detection), registra MCP server en `~/.claude.json`. `upgrade.sh` lee `~/.rufino/version`, compara con la versión del repo, aplica migraciones en `migrations/` en orden, hace backup previo en `~/.rufino/backups/<timestamp>/`.

**Tech Stack:** Bash POSIX, pip, jq (para editar `~/.claude.json`).

**Dependencias previas:** Plans 1-8 (todos los componentes a empaquetar).

**Plans que dependen de este:** ninguno — este es el último.

---

## File Structure

```
rufino-framework/
├── install.sh                          # bash POSIX
├── upgrade.sh                          # bash POSIX
├── migrations/                         # upgrade scripts por versión
│   └── README.md                       # convención de naming
├── README.md                           # quick start del repo
├── docs/
│   ├── adapters/                       # uno por shape
│   │   ├── worker-adapter.md
│   │   ├── vertical-config.md
│   │   ├── question-template.md
│   │   └── service-primitive.md        # explica que Query no tiene adapter shape
│   └── primitives/                     # uno por primitive
│       ├── ingest.md
│       ├── process.md
│       ├── output.md
│       ├── query.md
│       ├── memory-loop.md
│       └── qa-loop.md
└── tests/integration/
    └── test_install_smoke.sh           # bash smoke test del installer
```

---

## Task 1: README quick start

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Replace existing README with framework-oriented README**

Read current state first to know what's there. Then overwrite with:

```markdown
# Rufino Framework

> Meta-arquitectura A2P para construir productos de gestión de conocimiento personal a través de una conversación con Claude Code.

## Instalación

Requisitos: macOS o Linux, Python 3.11+, Claude Code CLI instalado y autenticado.

```bash
git clone https://github.com/<owner>/rufino-framework.git ~/rufino-framework
cd ~/rufino-framework
./install.sh
```

El instalador:
- Instala las dependencias Python (`pip install -e .`)
- Registra `rufino` en tu `$PATH`
- Crea `~/.rufino/` con la estructura base
- Registra el MCP server `ask-rufino` en `~/.claude.json`

Al terminar, te dice:

```
Listo. Para empezar, corré: rufino bootstrap
```

## Quick start

```bash
rufino bootstrap          # entrevista conversacional con Claude
                          # → al final, materializa tu vault
```

Después, usá tu vault como siempre: tirá notas a `inbox/`, conversá con
Claude Code en cualquier proyecto, recibí los digests por email.

## Comandos disponibles

| Comando | Para qué sirve |
|---|---|
| `rufino bootstrap` | Iniciar el wizard conversacional |
| `rufino version` | Imprimir la versión instalada |
| `rufino ingest <adapter>` | Correr un Ingest adapter una vez |
| `rufino process <note> --vault X --mode light` | Procesar una nota (light mode) |
| `rufino output <adapter>` | Correr un Output adapter una vez |
| `rufino query "..." --vault X` | Buscar en el vault |
| `rufino qa-poll --vault X --state-dir Y` | Procesar respuestas a preguntas |
| `rufino mcp-server --vault X` | Levantar MCP server stdio |
| `rufino install-memory-loop <adapter_dir> --vault X --claude-home Y` | Instalar un Memory loop adapter |
| `rufino materialize --spec <file> ...` | Materializar un vault desde una WizardSpec JSON |

## Upgrade

```bash
cd ~/rufino-framework
git pull
./upgrade.sh
```

## Documentación

- [Arquitectura del framework](docs/superpowers/specs/2026-05-16-rufino-framework-design.md)
- [Paper académico](docs/papers/2026-05-16-rufino-framework-paradigm-es.md)
- [Cómo escribir adapters](docs/adapters/)
- [API de las primitives](docs/primitives/)

## Licencia

(TBD por el dueño del repo privado.)
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs(distribution): framework-oriented README for quick start"
```

---

## Task 2: install.sh

**Files:**
- Create: `install.sh`

- [ ] **Step 1: Write installer**

`install.sh`:
```bash
#!/usr/bin/env bash
# Rufino Framework installer
# Idempotent: safe to re-run.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUFINO_HOME="${RUFINO_HOME:-$HOME/.rufino}"
CLAUDE_HOME="${CLAUDE_HOME:-$HOME/.claude}"

echo "==> Rufino Framework installer"
echo "    repo:        $REPO_DIR"
echo "    RUFINO_HOME: $RUFINO_HOME"
echo "    CLAUDE_HOME: $CLAUDE_HOME"
echo

# --- Step 1: Check Python
if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 not found. Install Python 3.11+ first." >&2
    exit 1
fi
PY_VERSION="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
echo "    python3:     $PY_VERSION"

# --- Step 2: Install Python package
echo "==> Installing Python dependencies"
python3 -m pip install --user -e "$REPO_DIR"

# --- Step 3: Add cli/ to PATH
SHELL_NAME="$(basename "$SHELL")"
case "$SHELL_NAME" in
    bash) RC="$HOME/.bashrc" ;;
    zsh)  RC="$HOME/.zshrc" ;;
    *)    RC="" ;;
esac

CLI_DIR="$REPO_DIR/cli"
PATH_LINE="export PATH=\"$CLI_DIR:\$PATH\"  # rufino-framework"

if [ -n "$RC" ]; then
    if ! grep -qF "$CLI_DIR" "$RC" 2>/dev/null; then
        echo "==> Adding $CLI_DIR to PATH in $RC"
        echo "" >> "$RC"
        echo "$PATH_LINE" >> "$RC"
    else
        echo "    PATH already configured in $RC (skip)"
    fi
else
    echo "    WARN: unknown shell '$SHELL_NAME'; add manually:" >&2
    echo "    $PATH_LINE" >&2
fi

# --- Step 4: Create ~/.rufino structure
echo "==> Creating $RUFINO_HOME structure"
mkdir -p "$RUFINO_HOME/state"
mkdir -p "$RUFINO_HOME/backups"
mkdir -p "$RUFINO_HOME/adapters/ingest"
mkdir -p "$RUFINO_HOME/adapters/process"
mkdir -p "$RUFINO_HOME/adapters/output"
mkdir -p "$RUFINO_HOME/adapters/memory_loop"
mkdir -p "$CLAUDE_HOME/hooks"
mkdir -p "$CLAUDE_HOME/commands"

# Track installed version
"$CLI_DIR/rufino" version > "$RUFINO_HOME/version"
echo "    version recorded: $(cat "$RUFINO_HOME/version")"

# --- Step 5: Register MCP server
CLAUDE_JSON="$HOME/.claude.json"
if command -v jq >/dev/null 2>&1; then
    if [ ! -f "$CLAUDE_JSON" ]; then
        echo "{}" > "$CLAUDE_JSON"
    fi
    if ! jq -e '.mcpServers["ask-rufino"]' "$CLAUDE_JSON" >/dev/null 2>&1; then
        echo "==> Registering MCP server ask-rufino in $CLAUDE_JSON"
        TMP="$(mktemp)"
        jq --arg cmd "$CLI_DIR/rufino" \
           '.mcpServers["ask-rufino"] = {
                command: $cmd,
                args: ["mcp-server", "--vault", "<set RUFINO_VAULT env>"]
            }' "$CLAUDE_JSON" > "$TMP"
        mv "$TMP" "$CLAUDE_JSON"
    else
        echo "    MCP server already registered (skip)"
    fi
else
    echo "    WARN: jq not installed — skipping MCP registration." >&2
    echo "    Add manually to $CLAUDE_JSON under .mcpServers" >&2
fi

echo
echo "==> Done."
echo
echo "Listo. Para empezar, abrí una shell nueva (o source $RC) y corré:"
echo "    rufino bootstrap"
```

- [ ] **Step 2: Make executable + commit**

Run: `chmod +x install.sh`

```bash
git add install.sh
git commit -m "feat(distribution): install.sh idempotent installer"
```

---

## Task 3: upgrade.sh + migrations directory

**Files:**
- Create: `upgrade.sh`
- Create: `migrations/README.md`

- [ ] **Step 1: Write upgrade.sh**

`upgrade.sh`:
```bash
#!/usr/bin/env bash
# Rufino Framework upgrade
# - reads installed version from ~/.rufino/version
# - compares to current repo version
# - backs up ~/.rufino/ to ~/.rufino/backups/<timestamp>/
# - runs migrations/<version>.sh in order

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUFINO_HOME="${RUFINO_HOME:-$HOME/.rufino}"
VERSION_FILE="$RUFINO_HOME/version"

if [ ! -f "$VERSION_FILE" ]; then
    echo "ERROR: $VERSION_FILE not found. Run ./install.sh first." >&2
    exit 1
fi

INSTALLED="$(cat "$VERSION_FILE")"
CURRENT="$("$REPO_DIR/cli/rufino" version)"

echo "==> Rufino Framework upgrade"
echo "    installed: $INSTALLED"
echo "    target:    $CURRENT"

if [ "$INSTALLED" = "$CURRENT" ]; then
    echo "==> Already at $CURRENT. Nothing to do."
    exit 0
fi

# --- Backup
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="$RUFINO_HOME/backups/$TIMESTAMP"
echo "==> Backing up $RUFINO_HOME to $BACKUP_DIR"
mkdir -p "$BACKUP_DIR"
# Exclude backups/ to avoid recursive copy
find "$RUFINO_HOME" -maxdepth 1 -mindepth 1 ! -name backups -exec cp -r {} "$BACKUP_DIR/" \;

# --- Reinstall Python package
echo "==> Reinstalling Python package"
python3 -m pip install --user -e "$REPO_DIR"

# --- Apply migrations in order
echo "==> Applying migrations"
MIGRATIONS_DIR="$REPO_DIR/migrations"
APPLIED_FILE="$RUFINO_HOME/applied-migrations"
touch "$APPLIED_FILE"

for migration in "$MIGRATIONS_DIR"/*.sh; do
    [ -f "$migration" ] || continue  # no migrations yet
    name="$(basename "$migration")"
    if grep -qF "$name" "$APPLIED_FILE"; then
        echo "    skip $name (already applied)"
        continue
    fi
    echo "    applying $name"
    bash "$migration"
    echo "$name" >> "$APPLIED_FILE"
done

# --- Update version marker
echo "$CURRENT" > "$VERSION_FILE"

echo "==> Upgrade complete: $INSTALLED → $CURRENT"
echo "    Backup: $BACKUP_DIR"
```

`migrations/README.md`:
```markdown
# Migrations

Each migration script is a bash file named `<from>-to-<to>.sh` (e.g. `0.0.1-to-0.1.0.sh`).

Migrations are applied in **lexicographic order** of filename, so always
prefix with semver-ordered names. The applied set is tracked in
`~/.rufino/applied-migrations` (one filename per line).

Each migration MUST be idempotent — `upgrade.sh` may be re-run after a
partial failure, and a migration that already ran half-way should be safe
to re-execute.

## Example migration

`migrations/0.0.1-to-0.1.0.sh`:
```bash
#!/usr/bin/env bash
set -euo pipefail
# Example: rename a state file
if [ -f "$HOME/.rufino/old-name.json" ]; then
    mv "$HOME/.rufino/old-name.json" "$HOME/.rufino/new-name.json"
fi
```

No migrations yet — directory is initially empty.
```

- [ ] **Step 2: Make executable + commit**

Run: `chmod +x upgrade.sh`

```bash
git add upgrade.sh migrations/README.md
git commit -m "feat(distribution): upgrade.sh + migrations convention"
```

---

## Task 4: Smoke test for installer

**Files:**
- Create: `tests/integration/test_install_smoke.sh`

- [ ] **Step 1: Write smoke test**

`tests/integration/test_install_smoke.sh`:
```bash
#!/usr/bin/env bash
# Integration smoke test of install.sh
# - runs installer with isolated HOME
# - verifies binary works
# - verifies ~/.rufino structure created
# Does NOT touch the user's real ~/.claude.json or ~/.rufino

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

TMPHOME="$(mktemp -d)"
trap 'rm -rf "$TMPHOME"' EXIT

echo "==> Smoke test using HOME=$TMPHOME"

HOME="$TMPHOME" \
    SHELL="/bin/bash" \
    RUFINO_HOME="$TMPHOME/.rufino" \
    CLAUDE_HOME="$TMPHOME/.claude" \
    bash "$REPO_DIR/install.sh"

# Verify structure
test -d "$TMPHOME/.rufino" || { echo "FAIL: ~/.rufino missing"; exit 1; }
test -d "$TMPHOME/.rufino/state" || { echo "FAIL: state/ missing"; exit 1; }
test -f "$TMPHOME/.rufino/version" || { echo "FAIL: version file missing"; exit 1; }

# Verify rufino runs
"$REPO_DIR/cli/rufino" version || { echo "FAIL: rufino version failed"; exit 1; }

echo "==> OK: install smoke passed"
```

- [ ] **Step 2: Make executable + run it**

Run: `chmod +x tests/integration/test_install_smoke.sh && bash tests/integration/test_install_smoke.sh`

Expected: `==> OK: install smoke passed`

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_install_smoke.sh
git commit -m "test(distribution): integration smoke for installer"
```

---

## Task 5: Docs por shape de adapter

**Files:**
- Create: `docs/adapters/worker-adapter.md`
- Create: `docs/adapters/vertical-config.md`
- Create: `docs/adapters/question-template.md`
- Create: `docs/adapters/service-primitive.md`

- [ ] **Step 1: Write each doc**

`docs/adapters/worker-adapter.md`:
```markdown
# Worker adapter

Shape usado por: **Ingest**, **Process**, **Output**.

## Estructura

```
~/.rufino/adapters/<primitive>/<adapter_name>/
├── manifest.yaml           # required
├── prompt.md               # required for Process; optional for Ingest emit_augmented
├── template.md             # required for Output
└── transform.py            # optional — solo si lógica determinista hace falta
```

## Manifest

Cada primitive define los campos requeridos. Ver `docs/primitives/<name>.md` para el schema exacto.

## transform.py

Opcional. Si declarado en el manifest, corre en sandbox después del LLM call (Process) o después del fetch (Ingest).

Firma única: `transform(input: dict) → dict`. Input vía stdin JSON, output vía stdout JSON.

## Validación

El framework valida cada manifest contra reglas de su primitive antes de instalar. Errores bloquean install; warnings loggean.
```

`docs/adapters/vertical-config.md`:
```markdown
# Vertical config adapter

Shape usado por: **Memory loop**.

## Estructura

```
~/.rufino/adapters/memory_loop/<adapter_name>/
├── manifest.yaml
└── rules/
    ├── <vertical>-vocabulary.md
    └── <vertical>-conventions.md
```

## Qué hace

A diferencia de los Worker adapters (que ejecutan código), el Vertical config es **declarativo + reglas para Claude**. El framework instala las reglas en `~/.claude/rules/common/` para que Claude las lea al iniciar conversación.

## Campos del manifest

- `adapter_name`, `vertical_name`
- `entity_types`: lista de tipos de notas que tu vertical maneja
- `note_destinations`: mapeo entity_type → path template
- `rule_extensions`: lista de paths a rules markdown

Ver `docs/primitives/memory-loop.md` para el schema completo.
```

`docs/adapters/question-template.md`:
```markdown
# Question template

Shape usado por: **Q&A loop**.

## Estructura

Un archivo único, sin carpeta:

```
~/.rufino/qa-templates/<template-name>.md
```

## Frontmatter requerido

```yaml
---
template_name: <snake_case>
required_context: [<field1>, <field2>, ...]
expected_answer: "<descripción del formato de respuesta>"
---
```

## Body

Markdown con placeholders jinja2 (`{{ field }}`, `{% for ... %}`). Los placeholders referencian fields del `required_context`.

El framework valida que cada `required_context` esté presente al renderizar.

## Cómo se invocan

Desde cualquier adapter que importe el QA helper:

```python
from rufino.engine.qa.api import QALoopAPI
api = QALoopAPI(...)
q_id = api.ask_user(
    template_name="materia_ambigua",
    context={"apunte_slug": "x", "candidate_materias": [...], "evidence": "..."},
    adapter_name="process-apunte-clase",
    adapter_state={...},
)
```
```

`docs/adapters/service-primitive.md`:
```markdown
# Service primitive (no adapter)

La **Query layer** no tiene shape de adapter — es una API pura del framework. Cualquier consumidor (CLI, MCP, Output adapter, Wizard) la importa directamente.

```python
from rufino.engine.query.api import QueryLayer

ql = QueryLayer(vault_root=path, embedder=embedder)
ql.rebuild_indices()

results = ql.search("regresión", mode="hybrid", k=10)
relations = ql.traverse(node="ml-i", relation="tema-de", depth=1, reverse=True)
```

## Por qué no tiene adapter

Los adapters existen para configurar comportamiento específico del vertical. La búsqueda y traversal del grafo son operaciones universales: no cambian entre verticales. Forzar un manifest sería ceremonia sin valor.
```

- [ ] **Step 2: Commit**

```bash
git add docs/adapters/
git commit -m "docs(distribution): adapter shape docs (4 shapes)"
```

---

## Task 6: Docs por primitive

**Files:**
- Create: `docs/primitives/ingest.md`
- Create: `docs/primitives/process.md`
- Create: `docs/primitives/output.md`
- Create: `docs/primitives/query.md`
- Create: `docs/primitives/memory-loop.md`
- Create: `docs/primitives/qa-loop.md`

- [ ] **Step 1: Write each doc as a thin pointer + schema reference**

Each doc follows the same shape: short description + schema fields + link to the relevant plan.

`docs/primitives/ingest.md`:
```markdown
# Ingest engine

Trae data de fuentes externas y la normaliza al vault. Tres `output_mode`:
- `emit_fact`: records atómicos en `<source>/facts/`
- `import_raw`: docs largos al inbox (dispara Process inmediato por default)
- `emit_augmented`: streaming directo a Process (deferido a v1.1)

## Manifest schema

```yaml
adapter_name: <kebab-case>
source_name: <slug>
schedule: "<cron-expression>"
auth: { type: oauth2 | api_key | none, keychain_service: <slug> }
output_mode: emit_fact | import_raw | emit_augmented

# emit_fact-specific:
emits: [<entity_type>, ...]
fact_schema: { <field>: <type>, ... }
destination:
  facts: <path-template>
  raw: <path-template>
dedup_by: <field-name>

# import_raw-specific:
target_inbox: <relative-path>
process_with: <process-adapter-name>
trigger: immediate | defer       # default: immediate

# optional:
transform_hook: ./transform.py
```

Ver [Plan 4](../superpowers/plans/2026-05-16-plan-4-ingest-engine.md) para el contrato completo + helpers.
```

`docs/primitives/process.md`:
```markdown
# Process pipeline

Augmenta notas crudas. Modos `full | light | lint`.

## Manifest schema

```yaml
adapter_name: <kebab-case>
note_type: <snake_case>
applies_when:
  source_dir: <relative-path>
  matches_pattern: ["*.pdf", "*.md", ...]
llm: sonnet | haiku | opus
mode_default: full | light
output_schema:
  required: { <field>: <type>, ... }
  optional: { <field>: <type>, ... }
triple_vocabulary: [<relation>, ...]
tag_axes:
  - { axis: <name>, format: "<axis>/<slug>", required: true | false, min: <int> }
destination_path: "<path-template-with-{frontmatter-fields}>"
qa_triggers:
  - { name: <name>, condition: "<expression>" }
context_injectors:
  - { name: <name>, query: "<query-expression>" }
transform_hook: ./transform.py            # optional
```

Ver [Plan 3](../superpowers/plans/2026-05-16-plan-3-process-pipeline.md).
```

`docs/primitives/output.md`:
```markdown
# Output dispatcher

Genera derivados del vault: digests, reportes, recomendaciones, alertas.

## Manifest schema

```yaml
adapter_name: <kebab-case>
trigger:
  type: cron | on_event
  expression: "<cron>"                    # if type=cron
  event: <event-name>                     # if type=on_event
  filter: "<expression>"                  # if type=on_event
query:
  - { name: <name>, expression: "<query>" }
template: ./templates/<name>.md
delivery:
  - { channel: file, path: "<path-template>" }
  - { channel: email, to: "<addr>", subject: "<subject>" }
  - { channel: webhook, url: "<url>" }
  - { channel: push, title: "<title>" }
```

Ver [Plan 5](../superpowers/plans/2026-05-16-plan-5-output-dispatcher.md).
```

`docs/primitives/query.md`:
```markdown
# Query layer

API unificada de lectura. Service primitive — no tiene shape de adapter.

## API

```python
search(query: str, mode: "lexical" | "semantic" | "hybrid", k: int) → [NoteRef]
traverse(node: str, relation: str, depth: int, reverse: bool) → [NoteRef]
```

Backends: ripgrep (lexical), Ollama+cosine (semántico), SQLite triple store (grafo).

Ver [Plan 7](../superpowers/plans/2026-05-16-plan-7-query-layer-mcp.md).
```

`docs/primitives/memory-loop.md`:
```markdown
# Memory loop

Integración con conversaciones de Claude Code en curso.

## Adapter shape

Vertical config — ver [docs/adapters/vertical-config.md](../adapters/vertical-config.md).

## Manifest schema

```yaml
adapter_name: <kebab-case>
vertical_name: <slug>
entity_types: [<type>, ...]
note_destinations:
  <type>: "<path-template>"
rule_extensions: [./rules/<vertical>-vocabulary.md, ./rules/<vertical>-conventions.md]
```

Ver [Plan 2](../superpowers/plans/2026-05-16-plan-2-memory-loop.md).
```

`docs/primitives/qa-loop.md`:
```markdown
# Q&A loop

Pipeline de preguntas que solo el user puede resolver.

## API

```python
api.ask_user(template_name, context, adapter_name, adapter_state) → question_slug
api.get_answer(slug) → answer | None
```

Worker poll dispatch:

```bash
rufino qa-poll --vault X --state-dir Y
```

Templates: ver [docs/adapters/question-template.md](../adapters/question-template.md).

Ver [Plan 6](../superpowers/plans/2026-05-16-plan-6-qa-loop.md).
```

- [ ] **Step 2: Commit**

```bash
git add docs/primitives/
git commit -m "docs(distribution): primitive docs (6 primitives)"
```

---

## Task 7: Final verification

- [ ] **Step 1: Run the install smoke test one more time**

Run: `bash tests/integration/test_install_smoke.sh`
Expected: `OK: install smoke passed`

- [ ] **Step 2: Run full Python test suite**

Run: `pytest -v`
Expected: all tests pass across all plans 1-9

- [ ] **Step 3: Verify CLI commands**

Run:
```bash
./cli/rufino version
./cli/rufino --help
./cli/rufino bootstrap --dry-run | head -5
```

Expected: version prints, help lists all commands (`bootstrap, materialize, version, install-memory-loop, process, ingest, output, qa-poll, query, mcp-server`), bootstrap dry-run prints system prompt.

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "chore: plan 9 final verification — all green"
```

---

## Self-review checklist

- [ ] install.sh is idempotent (safe to re-run)
- [ ] install.sh handles missing jq gracefully (warns, doesn't crash)
- [ ] upgrade.sh backs up before any change
- [ ] upgrade.sh tracks applied migrations in a file (not re-applied)
- [ ] All 4 adapter shape docs exist
- [ ] All 6 primitive docs exist
- [ ] README points to spec + paper + adapter docs
- [ ] Install smoke test runs in isolated $HOME

## Done criteria

- `bash install.sh` in a clean environment installs successfully
- `rufino bootstrap --dry-run` works post-install
- `bash upgrade.sh` on same-version install reports "Already at X. Nothing to do."
- All docs exist and link to the right plans
- Smoke test passes
