# Architecture

Overview de cómo está construido el framework por dentro. Apuntado a contribuidores que necesitan modificar primitives, agregar features al runtime, o entender por qué algo está como está.

## Mapa mental

```
                              ┌─────────────────┐
                              │   rufino CLI    │  ← fachada thin (cli.py)
                              └────────┬────────┘
                                       │
       ┌───────────────────────────────┴───────────────────────────────┐
       │                                                               │
   ┌───▼────┐  ┌────────┐  ┌────────┐  ┌────────┐  ┌─────────────┐  ┌──▼────────┐
   │ Ingest │  │Process │  │Output  │  │Query   │  │ Memory loop │  │  Q&A loop │
   │ engine │  │pipeline│  │dispatch│  │ layer  │  │             │  │           │
   └────┬───┘  └────┬───┘  └────┬───┘  └────┬───┘  └──────┬──────┘  └─────┬─────┘
        │           │           │           │             │               │
        └───────────┴───────────┴───────────┴─────────────┴───────────────┘
                                       │
                                       │  toda mutación al disco /
                                       │  keychain / launchd pasa por:
                                       │
                              ┌────────▼────────┐
                              │  Runtime        │
                              │  ─ tx log       │
                              │  ─ sandbox      │
                              │  ─ scheduler    │
                              │  ─ secrets      │
                              │  ─ validators   │
                              └────────┬────────┘
                                       │
                              ┌────────▼────────┐
                              │  Filesystem +   │
                              │  Keychain +     │
                              │  launchd/cron   │
                              │  + vault MD     │
                              └─────────────────┘
```

## Las 6 primitives

| Primitive | Path | Adapter shape | Doc |
|---|---|---|---|
| **Ingest** | `src/rufino/engine/ingest/` | Worker adapter | [primitives/ingest.md](primitives/ingest.md) |
| **Process** | `src/rufino/engine/process/` | Worker adapter | [primitives/process.md](primitives/process.md) |
| **Output** | `src/rufino/engine/output/` (channels en `output/channels/`) | Worker adapter | [primitives/output.md](primitives/output.md) |
| **Query** | `src/rufino/engine/query/` | Service primitive (sin adapter) | [primitives/query.md](primitives/query.md) |
| **Memory loop** | `src/rufino/engine/memory_loop/` | Vertical config | [primitives/memory-loop.md](primitives/memory-loop.md) |
| **Q&A loop** | `src/rufino/engine/qa/` | Question template | [primitives/qa-loop.md](primitives/qa-loop.md) |

Cada engine tiene una **forma similar pero no idéntica**:

```
engine/<primitive>/
├── __init__.py
├── manifest.py         # parser + validador del manifest de adapter
├── dispatcher.py       # el "ejecutor" (a veces se llama runner.py o api.py)
├── api.py              # API pública del primitive (Query y Q&A la usan; otras la implícita)
└── <helpers específicos del primitive>
```

Diferencias:

- **Query** no tiene `manifest.py` ni `dispatcher.py` — es API pura. Tiene `api.py` + `backends/*` + `filters.py`.
- **Process** tiene `context_injectors.py`, `frontmatter.py`, `triples.py`, etc. — helpers del augmentation pipeline.
- **Output** tiene `channels/` (file, email, webhook, push) — uno por delivery channel.
- **Memory loop** tiene `installer.py` que maneja el copy de reglas + hooks a `~/.claude/`.

## La heterogeneidad de adapter shapes

| Shape | Primitives | Estructura | Justificación |
|---|---|---|---|
| **Worker adapter** | Ingest, Process, Output | Carpeta con `manifest.yaml` + `prompt.md`/`template.md` + opcional `transform.py` | Los 3 corren código + LLM + producen output → necesitan templates + schema |
| **Service primitive** | Query | API pura, sin adapter | La búsqueda no varía entre verticales — forzar un manifest sería ceremonia |
| **Vertical config** | Memory loop | Carpeta con `manifest.yaml` + `rules/*.md` | Las reglas son para Claude, no código — markdown + frontmatter es la forma natural |
| **Question template** | Q&A loop | Archivo único: markdown + jinja2 + frontmatter | Una pregunta es un template — no amerita una carpeta entera |

Detalle de cada uno: [`adapters/`](adapters/).

## El CLI es una fachada

`src/rufino/cli.py` (≈300 líneas) es intencionalmente thin. Un comando típico se ve así:

```python
@cli.command(name="ingest")
@click.argument("adapter_dir", ...)
@click.option("--vault", ...)
@click.option("--state-dir", ...)
def ingest_cmd(adapter_dir, vault_root, state_dir):
    """Run an Ingest adapter once."""
    result = run_ingest(
        adapter_dir=adapter_dir,
        vault_root=vault_root,
        rufino_state_dir=state_dir,
    )
    click.echo(f"adapter={result.adapter_name} emitted={result.facts_emitted} ...")
```

Toda la orquestación vive en `run_ingest()` (en `engine/ingest/runner.py`). Si encontrás vos mismo agregando branching de negocio al CLI, empujalo al engine.

**Beneficios:**
- El comportamiento es testeable sin pasar por Click.
- Múltiples consumers (CLI, MCP, programmatic) usan el mismo engine.
- El CLI puede cambiar sin tocar lógica.

## El transaction log: la abstracción load-bearing

`src/rufino/runtime/transaction_log.py` es **la pieza más importante del framework**. Cualquier mutación al disco / keychain / launchd que pase durante materialización o installer pasa por acá.

Forma:

```python
from rufino.runtime.transaction_log import TransactionLog, apply_and_log

tx_log = TransactionLog(path=tx_log_path)

apply_and_log(
    tx_log,
    op="mkdir",
    target="/Users/beto/facultad",
    apply_fn=lambda: Path("/Users/beto/facultad").mkdir(parents=True),
    rollback="rmdir_if_empty",
)
# ... más operaciones ...

# Si algo falla:
tx_log.rollback()    # ejecuta los inversos en orden reverso
```

Cada `apply_and_log` **primero** escribe al log JSON (con `fsync` + atomic rename para que el log sea válido aún si el proceso muere antes del flush) y **después** ejecuta la operación. Si la operación falla, el log queda con la entrada — pero el rollback handler tiene que ser idempotente (ej: `rmdir_if_empty` no se queja si el dir no existe).

**Rollback handlers** registrados (mirá `transaction_log.py:39`):
- `rmdir` — borra dir vacío
- `rmdir_if_empty` — borra dir solo si está vacío (más seguro)
- `delete` — borra archivo
- `keychain_delete` — borra entry del Keychain
- `plist_uninstall` — `launchctl unload && rm` un plist

Si agregás un nuevo tipo de mutación al disco/sistema, **tenés que** registrar su rollback handler con `register_rollback(name, fn)`. Si no lo hacés, el rollback de esa op va a fallar silencioso.

Más detalle: [`runtime.md#transaction-log`](runtime.md#transaction-log).

## Estructura del repo

```
rufino-framework/
├── README.md                        # entrypoint del repo
├── CLAUDE.md                        # onboarding para sesiones de Claude Code
├── install.sh, upgrade.sh           # entrypoints user
├── pyproject.toml                   # metadata package + CLI binding (script: rufino)
├── migrations/                      # bash scripts idempotentes para upgrades
│   └── README.md                    # contrato de migrations
├── src/rufino/                      # ← el código
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py                       # CLI Click (fachada thin)
│   ├── version.py                   # VERSION = "0.1.0"
│   ├── engine/                      # las 6 primitives
│   │   ├── ingest/
│   │   ├── process/
│   │   ├── output/{channels/}
│   │   ├── query/{backends/}
│   │   ├── memory_loop/
│   │   └── qa/
│   ├── wizard/                      # bootstrap conversacional
│   │   ├── patterns/                # 6 .md files (uno por pattern)
│   │   ├── auto_detect.sh
│   │   ├── checklist.md
│   │   ├── language_rules.md
│   │   ├── operative_rules.md
│   │   ├── system_prompt_assembler.py
│   │   ├── spec_schema.py
│   │   ├── materializer.py
│   │   └── post_bootstrap_docs.py
│   ├── runtime/                     # plumbing cross-cutting
│   │   ├── transaction_log.py       # ← LOAD-BEARING
│   │   ├── secrets.py               # Keychain abstraction
│   │   ├── scheduler.py             # launchd / cron / systemd
│   │   ├── sandbox.py               # subprocess sandbox (parcial)
│   │   ├── prereq_checker.py
│   │   ├── validator_base.py
│   │   └── claude_config.py         # mcp registration helpers
│   ├── mcp_server/                  # ask-rufino MCP server (stdio)
│   │   ├── server.py
│   │   └── tools.py
│   └── helpers/                     # versioned helper API for adapters
│       └── v1/
├── vault-skeleton/                  # bootstrap del vault del usuario
├── system/launchd/                  # plists templates para macOS scheduler
├── claude/                          # hooks/commands/skills que se copian a ~/.claude/
├── tests/                           # pytest
│   ├── conftest.py                  # tmp_vault + tmp_rufino_home fixtures
│   ├── test_*.py                    # unit tests (mirror del módulo)
│   └── integration/                 # smoke tests cross-engine
└── docs/                            # esto
```

## Versioning y migrations

`upgrade.sh` se keya en `rufino version`, que devuelve `src/rufino/version.py:VERSION`. **Cambios sin bump de versión son invisibles al upgrade** — imprime `Already at X. Nothing to do.`

Bumpeá:
- `src/rufino/version.py:VERSION = "x.y.z"`
- `pyproject.toml:version = "x.y.z"`

Migrations en `migrations/`:
- Nombradas `<from>-to-<to>.sh`
- Corren en orden lexicográfico
- Idempotentes (el upgrade puede re-correr después de partial failure)
- Corren **contra el código nuevo** (pipx reinstall ya pasó) — pero las migrations no pueden importar el código, leen state files directo de disco
- Se trackean por filename en `~/.rufino/applied-migrations`

Detalle: [`upgrading.md`](upgrading.md).

## Tests

Convenciones:

- **Unit tests** en `tests/test_*.py` espejan la estructura del módulo:
  - `tests/test_ingest_*.py` testean cosas de `engine/ingest/`
  - `tests/test_process_*.py` testean cosas de `engine/process/`
  - etc.
- **Integration tests** en `tests/integration/`.
- **Fixtures comunes** en `tests/conftest.py`: `tmp_vault`, `tmp_rufino_home`. Usalas en vez de armar tu propio tmp setup.
- **Tests de rollback obligatorios para ops nuevas.** Cuando agregás una op que toca disco/keychain/launchd, tenés que agregar un test que la haga fallar a la mitad y verifique que el rollback ejecuta limpio.

Correr tests:

```bash
.venv/bin/python -m pytest                    # todo
.venv/bin/python -m pytest tests/test_cli_process.py
.venv/bin/python -m pytest -k qa_worker
.venv/bin/python -m pytest --cov=src --cov-report=term-missing
```

**Importante:** **NO uses `python3 -m pytest`** — el system Python no tiene las deps del proyecto y la collection rompe en `test_secrets.py` (`ModuleNotFoundError: No module named 'keyring'`). Usá siempre el del `.venv` local.

## Cosas deferidas a propósito

Estas no son bugs — son features con plan referenciado, no implementadas en v0.1.0:

| Pieza | Estado | Plan |
|---|---|---|
| `transform.py` (escape hatch de código determinista) | Manifest acepta y parsea `transform_hook`, runner no lo invoca | TBD |
| Ingest `output_mode: emit_augmented` | Manifest parsea, dispatcher inline no wireado | TBD |
| Single-note `rufino process --mode full` | CLI exits 2; usá `process-batch` para procesar en lote | Reviving stays out of scope |
| Embedder real (Ollama + nomic-embed-text) | Placeholder `_NoopEmbeddings` que tira NotImplementedError | TBD — plan referenciado |

Si encontrás algo que parece roto pero está en esta tabla, **no es bug** — revisá el plan referenciado.

## Decisiones arquitectónicas clave

Por qué algunas cosas son como son.

### Por qué 4 shapes de adapter heterogéneos, no uno uniforme

Forzar uniformidad (ej: que Q&A templates vivan en carpetas con manifest.yaml + template.md) genera ceremonia sin valor. Cada primitive tiene la shape que naturalmente le encaja. La heterogeneidad es honesta: el código está más limpio y el adapter author tiene menos boilerplate.

### Por qué un transaction log explícito, no try/except

Las operaciones de bootstrap involucran disco + keychain + launchd. El cleanup parcial con try/except es frágil — fácil olvidarse de uno, fácil que el rollback no sea idempotente. Un tx log explícito centraliza la responsabilidad, fuerza al desarrollador a declarar el rollback junto a la op, y permite tracking + auditoría.

### Por qué el wizard es conversacional libre, no fases ordenadas

Fases ordenadas con preguntas pre-escritas serían más predecibles pero menos naturales. La filosofía del framework es "no construyas tu sistema, conversá" — un wizard rígido contradice eso. La calidad depende del juicio de Claude (variable) pero el techo es más alto.

### Por qué big bang, no saves intermedios

Saves intermedios significan vault a medio armar — que el usuario puede encontrar después y no entender en qué estado está. Big bang transaccional garantiza que el vault siempre está en un estado válido. Si la conversación se interrumpe, el rollback automático deja todo como estaba.

### Por qué markdown + frontmatter, no DB

El vault es la fuente de verdad. Markdown + YAML frontmatter es:
- Inspeccionable a mano (cat, grep, git diff)
- Versionable (git)
- Portable (Obsidian, VSCode, vim)
- Sin lock-in

Los indices (triple store SQLite, embeddings SQLite) son **derivados** — rebuildeables desde el vault. Si la DB se corrompe, `rebuild_indices()` la reconstruye. El vault sobrevive a cambios de runtime.

### Por qué pipx, no pip --user

PEP 668 en Python 3.14 + Homebrew bloquea `pip install --user --break-system-packages` por default. pipx aisla cada app en su propio venv — más limpio, más reproducible, evita conflictos entre packages.

Aprendizaje arquitectónico capturado en el vault: ver `pythonPackagingPep668.md`.

## Cómo contribuir

1. Leé el código del primitive / runtime que vas a tocar y los tests existentes antes de cambiar nada.
2. TDD — escribí el test antes que el código.
3. Si tocás algo que muta disco/keychain/launchd, agregá una rollback test.
4. Bumpeá la versión + agregá la migration si aplica.
5. Code review pre-merge — agentes paralelos (`pr-review-toolkit:code-reviewer`) para PRs grandes.
6. Merge a `main` con `--no-ff`, branch local borrada después.

Convenciones del repo en [CLAUDE.md](../CLAUDE.md) (raíz del repo).
