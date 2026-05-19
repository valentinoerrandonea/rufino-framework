# CLI reference

Referencia completa de cada comando `rufino`. Para ver flags rápidos: `rufino <cmd> --help`.

El CLI es una fachada thin sobre los engines (`src/rufino/cli.py`). Cada comando delega la orquestación al engine correspondiente.

---

## `rufino version`

```bash
rufino version
```

Imprime la versión instalada. Sin flags.

Output: línea única con la versión (ej: `0.1.0`).

Implementado en `src/rufino/cli.py` (`version` command); valor leído de `src/rufino/version.py:VERSION`.

---

## `rufino bootstrap`

```bash
rufino bootstrap [--dry-run]
```

Arranca el wizard conversacional. Por default lanza una sesión interactiva con `claude --system-prompt <system-prompt> --allowedTools "..." -- "<kickoff>"` (NO `-p`/headless — el wizard requiere back-and-forth). Toolset restringido a `Read, Write, Bash(rufino materialize:*), Bash(rufino query:*)`.

Flags:

| Flag | Default | Qué hace |
|---|---|---|
| `--dry-run` | `false` | Imprime el system prompt a stdout en vez de lanzar `claude` |

Errores comunes:

- **`Error: 'claude' CLI no encontrado en PATH.`** — Instalá Claude Code (`brew install claude` o seguí [docs.claude.com/claude-code](https://docs.claude.com/claude-code)).
- Otros errores propagan el exit code de `claude`.

Detalle de cómo funciona el wizard: [`wizard.md`](wizard.md).

---

## `rufino materialize`

```bash
rufino materialize \
    --spec <FILE> \
    --vault <PATH> \
    --claude-home <PATH> \
    --state-dir <PATH>
```

Materializa el sistema descrito en una `WizardSpec` JSON. Normalmente lo invoca el wizard al cierre, pero podés correrlo a mano con un spec armado manualmente (modo experto).

Flags:

| Flag | Required | Qué hace |
|---|---|---|
| `--spec FILE` | sí | Path a una `WizardSpec` JSON |
| `--vault PATH` | sí | Path donde materializar el vault del usuario |
| `--claude-home PATH` | sí | Path al `~/.claude/` del usuario (memory loop se instala acá) |
| `--state-dir PATH` | sí | Path donde guardar el state del framework (típico: `~/.rufino/state`) |
| `--install-hooks` / `--no-install-hooks` | no | Instalar los hooks de Claude Code que capturan conversaciones a este vault. Opt-in (default: `--no-install-hooks`) |

Lo que hace:

1. Lee y valida el spec con `validate_spec()`. Si es inválido, exit 1 con `SpecError`.
2. Llama `materialize(spec, vault_root, claude_home, state_dir, install_hooks=...)`:
   - Crea el vault skeleton
   - Escribe `perfil.md` desde el spec
   - Materializa cada adapter (Ingest, Process, Output, Memory loop)
   - Instala el memory loop en `claude_home` **solo si `--install-hooks`**
   - Todo dentro de un `TransactionLog` — falla → rollback completo
3. Siempre: registra un MCP server **per-vault** (`ask-rufino-<slug>`, donde `<slug>` deriva del basename del vault) en `~/.claude.json` apuntando al vault recién creado. Esto permite que coexistan múltiples vaults sin pisarse.

Exit codes:

| Code | Significado |
|---|---|
| 0 | OK — vault materializado y MCP registrado |
| 1 | Spec inválido |
| 2 | Materialización falló (rollback ejecutado) |

Output OK:

```
Vault materialized at /Users/beto/facultad
Registered ask-rufino-facultad MCP at /Users/beto/.claude.json
```

---

## `rufino install-memory-loop`

```bash
rufino install-memory-loop <adapter_dir> \
    --vault <PATH> \
    --claude-home <PATH>
```

Instala un Memory loop adapter en `~/.claude/`. Subcomando útil cuando agregás un memory loop nuevo a un vault que ya existía.

Flags:

| Flag | Required | Qué hace |
|---|---|---|
| `adapter_dir` | sí | Carpeta del adapter (con `manifest.yaml` + `rules/`) |
| `--vault PATH` | sí | Path al vault del usuario |
| `--claude-home PATH` | sí | Path al `~/.claude/` del usuario |

Crea un `TransactionLog` en `<claude_home>/tx/install-memory-loop-<adapter_name>.json`. Si falla, dispara rollback.

Exit codes:

| Code | Significado |
|---|---|
| 0 | Instalado |
| 1 | Falló (rollback ejecutado) |

Detalle del shape "Vertical config" (lo que es un memory loop adapter): [`adapters/vertical-config.md`](adapters/vertical-config.md).

---

## `rufino ingest`

```bash
rufino ingest <adapter_dir> \
    --vault <PATH> \
    --state-dir <PATH>
```

Corre un Ingest adapter una vez (típicamente lo llama el scheduler — esto es para testing o trigger manual).

Flags:

| Flag | Required | Qué hace |
|---|---|---|
| `adapter_dir` | sí | Carpeta del adapter (con `manifest.yaml` + opcional `fetcher.py`) |
| `--vault PATH` | sí | Path al vault del usuario |
| `--state-dir PATH` | sí | Path donde persistir cursor + dedup state |

Output:

```
adapter=<name> emitted=<N> skipped=<N> errors=<N>
```

Si `errors > 0`, cada error sale a stderr.

**Importante:** el cursor **no avanza** si el run tuvo errores — eso garantiza idempotencia. Volvé a correr cuando arregles la causa.

Detalle del primitive: [`primitives/ingest.md`](primitives/ingest.md).

---

## `rufino process`

```bash
rufino process <note_path> \
    --vault <PATH> \
    --mode {light|full|lint} \
    [--adapter-dir <PATH>]
```

Procesa una nota.

Flags:

| Flag | Required | Default | Qué hace |
|---|---|---|---|
| `note_path` | sí | — | Path a la nota markdown |
| `--vault PATH` | sí | — | Path al vault del usuario |
| `--mode {light,full,lint}` | no | `light` | Modo de processing |
| `--adapter-dir PATH` | sí si `--mode full` | — | Carpeta del adapter Process |

Modos:

- **`light`** (operativo): solo update de indices + file move + frontmatter completion. Sin LLM, sin transform hook, sin Q&A. Útil para notas que vos / Claude escribieron a mano y solo necesitan ser registradas + linkeadas.
- **`full`** (operativo desde v0.2.0): pipeline completo single-note con LLM call, context injection, validation, transform hook, Q&A check, indices update. Internamente stagea la nota en un tempdir-of-one y delega a `run_batch` con `workers=1, batch_size=1`. Para procesar un corpus en lote usá [`rufino process-batch`](#rufino-process-batch).
- **`lint`** (operativo): valida sin modificar — chequea triple_vocabulary, frontmatter schema, wikilinks rotos.

Exit codes:

| Code | Significado |
|---|---|
| 0 | OK |
| 1 | Argumentos inválidos o failure de procesamiento |
| 3 | Q&A pendiente — revisá `<vault>/questions/` y corré `rufino qa-poll` |
| 127 | `claude` no encontrado en `$PATH` |

Detalle del primitive: [`primitives/process.md`](primitives/process.md).

---

## `rufino process-batch`

Procesa un corpus entero (directorio o ZIP) generando notas augmentadas
en paralelo vía workers de Claude.

### Sinopsis

    rufino process-batch <source> [options]

### Argumentos

- `<source>` — directorio o archivo `.zip` con el corpus a procesar.

### Opciones

| Flag | Descripción | Default |
|---|---|---|
| `--adapter <dir>` | Worker adapter a usar | (último materializado) |
| `--vault <dir>` | Vault destino | `$RUFINO_VAULT` |
| `--workers <N>` | Workers paralelos | `min(4, n_workers)` |
| `--batch-size <N>` | Notas por worker (override del manifest) | manifest |
| `--dry-run` | Solo stage + plan, sin ejecutar workers | `False` |
| `--skip-consolidator` | Saltea consolidador y usa naive plan | `False` |

### Exit codes

- `0` — run completo, commit aplicado.
- `1` — error de runtime (corpus vacío, manifest inválido, batch failure).
- `124` — un worker hizo timeout.
- `127` — `claude` binary no encontrado en PATH.
- session-expired — exit code 1 con mensaje pidiendo `claude login`.

### Ejemplos

    rufino process-batch ~/Downloads/corpus.zip \
      --adapter ~/.rufino/adapters/process/notas \
      --vault ~/vault --workers 4

    rufino process-batch ./corpus --dry-run

---

## `rufino output`

```bash
rufino output <adapter_dir> --vault <PATH>
```

Corre un Output adapter una vez (típicamente lo llama el scheduler — esto es para testing o trigger manual).

Flags:

| Flag | Required | Qué hace |
|---|---|---|
| `adapter_dir` | sí | Carpeta del adapter (con `manifest.yaml` + `template.md`) |
| `--vault PATH` | sí | Path al vault del usuario |

Nota: el query adapter inyectado (`_LexicalQueryAdapter`) usa el backend lexical. Si tu Output expression necesita similitud semántica, llamá `rufino query --mode semantic` desde un trigger externo y templatá sobre el resultado — los Output adapters no consumen `semantic`/`hybrid` directamente.

Output:

```
adapter=<name> deliveries=<N> errors=<N>
```

Detalle del primitive: [`primitives/output.md`](primitives/output.md).

---

## `rufino qa-poll`

```bash
rufino qa-poll \
    --vault <PATH> \
    --state-dir <PATH>
```

Recorre `<vault>/questions/` buscando preguntas con `answer:` no vacía y dispatcha sus callbacks registrados.

Flags:

| Flag | Required | Qué hace |
|---|---|---|
| `--vault PATH` | sí | Path al vault |
| `--state-dir PATH` | sí | Path al state dir (donde vive `callbacks.json`) |

`qa-poll` resuelve preguntas originadas en `process-batch`: detecta `answer:` no vacíos en `<vault>/questions/`, retoma el worker con la respuesta inyectada, y archiva la pregunta a `questions/answered/` (ver el primitive doc para el detalle del flujo).

Exit codes:

| Code | Significado |
|---|---|
| 0 | OK — sin pending o resumption aplicada |
| 2 | Hay answers pendientes para adapters que no soportan resumption todavía |

Detalle del primitive: [`primitives/qa-loop.md`](primitives/qa-loop.md).

---

## `rufino query`

```bash
rufino query "<query>" \
    --vault <PATH> \
    --mode {lexical|semantic|hybrid}
```

Busca en el vault. Output: lista de paths relativos al vault, uno por línea.

Flags:

| Flag | Required | Default | Qué hace |
|---|---|---|---|
| `query_string` | sí | — | El string a buscar |
| `--vault PATH` | sí | — | Path al vault (debe existir) |
| `--mode {lexical,semantic,hybrid}` | no | `hybrid` | Backend a usar |
| `--state-dir PATH` | no | `~/.rufino/state` | State dir donde vive `vaults/<slug>.yaml` |

`semantic` y `hybrid` son **opt-in (v0.2.0+)**: requieren `rufino enable-embeddings --vault <X>` previo (Ollama + `nomic-embed-text` corriendo). Si embeddings están disabled, el CLI exits con código 2 y un mensaje accionable. `lexical` siempre funciona.

Detalle del primitive: [`primitives/query.md`](primitives/query.md).

---

## `rufino mcp-server`

```bash
rufino mcp-server --vault <PATH> [--no-rebuild]
```

Levanta el MCP server por stdio. Normalmente lo invoca Claude Code (registrado en `~/.claude.json` como `ask-rufino-<slug>` por el wizard / installer), no vos a mano. Cada vault tiene su propio entry — pasá `--vault` apuntando al que querés consultar.

Flags:

| Flag | Required | Default | Qué hace |
|---|---|---|---|
| `--vault PATH` | sí | — | Path al vault (debe existir) |
| `--rebuild` / `--no-rebuild` | no | `--rebuild` | Reconstruir índices semantic+graph al startup |

`--no-rebuild` es útil si tenés el vault muy grande y querés evitar el costo de rebuild en cada arranque del MCP — pero el primer arranque siempre necesita `--rebuild` para popular la DB.

El server queda corriendo hasta que se cierra el stdio (Claude Code lo maneja por vos).

Tools que expone: `search_vault`, `read_note`, `traverse_relations`, `list_persons`, `list_concepts`, `vault_info` (6+ tools — ver `src/rufino/mcp_server/tools.py`).

---

## `rufino detect-embeddings`

```bash
rufino detect-embeddings
```

Chequea si Ollama está corriendo localmente y si el modelo `nomic-embed-text` está disponible. No modifica nada — solo reporta. Útil antes de `enable-embeddings` para diagnosticar por qué falla.

---

## `rufino enable-embeddings`

```bash
rufino enable-embeddings --vault <PATH> [--state-dir <PATH>] [--model <name>]
```

Activa el embedder semántico para un vault específico. Detecta Ollama, escribe la config en `<state-dir>/vaults/<slug>.yaml` con `embeddings.enabled: true`, y reconstruye los índices (semantic + graph). Si la detección falla (Ollama down / modelo no pulled), exits 1 y **no** escribe state.

| Flag | Required | Default | Qué hace |
|---|---|---|---|
| `--vault PATH` | sí | — | Vault a habilitar |
| `--state-dir PATH` | no | `~/.rufino/state` | Donde vive `vaults/<slug>.yaml` |
| `--model NAME` | no | `nomic-embed-text` | Modelo Ollama a usar |

---

## `rufino disable-embeddings`

```bash
rufino disable-embeddings --vault <PATH> [--state-dir <PATH>]
```

Vuelve `embeddings.enabled` a `false`. Idempotente. `--state-dir` default `~/.rufino/state`.

### Hybrid rerank — cross-encoder pinneado

El modo `hybrid` rerankea la unión `lex + sem` con un cross-encoder
(`BAAI/bge-reranker-base`). El modelo está pinneado por revisión en
`src/rufino/runtime/embedder/cross_encoder.py:_DEFAULT_REVISION` para
asegurar reproducibilidad: el primer query híbrido descarga ~400 MB la
primera vez, luego usa cache local de Hugging Face.

Variables de entorno opcionales:

- `RUFINO_RERANKER_MODEL` — sobreescribe el modelo (default `BAAI/bge-reranker-base`).
- `RUFINO_RERANKER_REVISION` — sobreescribe el commit SHA pineado.

Si el cross-encoder falla en runtime (lib no instalada, red caída,
RAM/VRAM insuficiente) `query` degrada a la unión sin rerank y loggea
una advertencia, sin crashear.

---

## `rufino install-ingest`

```bash
rufino install-ingest <adapter_dir> --vault <PATH> [--rufino-home <PATH>]
```

Materializa el cron del manifest de un Ingest adapter al scheduler del OS (`launchd` en macOS, `cron` en Linux). El job id queda como `rufino-ingest-<vault-slug>-<adapter-name>` para evitar colisiones cross-vault.

| Flag | Required | Default | Qué hace |
|---|---|---|---|
| `adapter_dir` | sí | — | Directorio del Ingest adapter (con `manifest.yaml`) |
| `--vault PATH` | sí | — | Vault al que pertenece este ingest |
| `--rufino-home PATH` | no | `~/.rufino` | Rufino home (usado para `logs/`) |

---

## `rufino uninstall-ingest`

```bash
rufino uninstall-ingest <adapter_name> --vault <PATH>
```

Remueve el job scheduled correspondiente a `<vault-slug>-<adapter-name>`.

---

## `rufino list-ingests`

```bash
rufino list-ingests
```

Lista los jobs `rufino-ingest-*` instalados en el scheduler del OS, uno por línea.

---

## Variables de entorno

| Variable | Default | Qué hace |
|---|---|---|
| `RUFINO_HOME` | `~/.rufino` | Path al state dir del framework (el installer y upgrade lo respetan) |
| `RUFINO_VAULT` | (no set) | Si está exportada al correr `install.sh`, el installer registra el MCP server con ese path |
| `RUFINO_FORCE` | `0` | Si `=1`, `upgrade.sh` acepta downgrades (riesgoso — no se aplica para uso normal) |
| `PIPX_BIN_DIR` | (de pipx) | Si está set, `install.sh`/`upgrade.sh` la usan en vez de llamar `pipx environment` |

## Exit codes (convención global)

| Code | Significado |
|---|---|
| 0 | OK |
| 1 | Argumentos / spec / config inválido (input del usuario), o failure de procesamiento |
| 2 | Feature opt-in disabled (ej. `--mode semantic` con embeddings off), o spec invalida en `materialize` |
| 3 | Q&A pendiente — usuario debe contestar en `<vault>/questions/` y correr `qa-poll` |
| 127 | Dependency externa faltante (`claude` CLI no encontrado, etc.) |
