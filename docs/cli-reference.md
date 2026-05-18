# CLI reference

Referencia completa de cada comando `rufino`. Para ver flags rápidos: `rufino <cmd> --help`.

El CLI es una fachada thin sobre los engines (`src/rufino/cli.py`). Cada comando delega la orquestación al engine correspondiente.

---

## `rufino version`

```bash
rufino version
```

Imprime la versión instalada. Sin flags.

Output: línea única con la versión (ej: `0.0.2`).

Implementado en `src/rufino/cli.py` (`version` command); valor leído de `src/rufino/version.py:VERSION`.

---

## `rufino bootstrap`

```bash
rufino bootstrap [--dry-run]
```

Arranca el wizard conversacional. Por default lanza `claude -p <system-prompt>` con toolset restringido (`Read, Write, Bash(rufino materialize:*), Bash(rufino query:*)`).

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

Lo que hace:

1. Lee y valida el spec con `validate_spec()`. Si es inválido, exit 1 con `SpecError`.
2. Llama `materialize(spec, vault_root, claude_home, state_dir)`:
   - Crea el vault skeleton
   - Escribe `perfil.md` desde el spec
   - Materializa cada adapter (Ingest, Process, Output, Memory loop)
   - Instala el memory loop en `claude_home`
   - Todo dentro de un `TransactionLog` — falla → rollback completo
3. Si OK: registra el MCP server `ask-rufino` en `~/.claude.json` apuntando al vault recién creado

Exit codes:

| Code | Significado |
|---|---|
| 0 | OK — vault materializado y MCP registrado |
| 1 | Spec inválido |
| 2 | Materialización falló (rollback ejecutado) |

Output OK:

```
Vault materialized at /Users/beto/facultad
Registered ask-rufino MCP at /Users/beto/.claude.json
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

- **`light`** (operativo en v0.0.2): solo update de indices + file move + frontmatter completion. Sin LLM, sin transform hook, sin Q&A. Útil para notas que vos / Claude escribieron a mano y solo necesitan ser registradas + linkeadas.
- **`full`** (stubbed en v0.0.2 — exits 2): pipeline completo con LLM call, context injection, validation, transform hook, Q&A check, indices update. **El CLI wiring de `--mode full` aterriza cuando se cierre la integración LLM + Query real.**
- **`lint`** (operativo): valida sin modificar — chequea triple_vocabulary, frontmatter schema, wikilinks rotos.

Exit codes:

| Code | Significado |
|---|---|
| 0 | OK |
| 1 | Argumentos inválidos |
| 2 | `--mode full` requiere wiring deferido |

Detalle del primitive: [`primitives/process.md`](primitives/process.md).

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

Limitación v0.0.2: el query backend usado es **solo lexical** (placeholder `_NoopEmbeddings` hasta que aterrice Ollama). Si tu Output query expression requiere semántica, va a fallar.

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

Limitación v0.0.2: el resumption real de adapters está pendiente. El handler interno levanta `_ResumptionNotImplemented` (a propósito — para no consumir el answer del usuario), así que `dispatched` siempre vuelve `0`. Si hay alguna pregunta con answer pendiente, el comando exits 2 y los archivos quedan intactos para retry.

Exit codes:

| Code | Significado |
|---|---|
| 0 | OK, sin pending |
| 2 | Hay answers pendientes que no se pueden dispatchar (resumption deferred) |

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

Limitación v0.0.2: **solo `--mode lexical` funciona**. `--mode semantic` y `--mode hybrid` requieren un embedder real (Ollama + `nomic-embed-text`) que está deferido — el CLI exits con código 2 y un mensaje claro.

Cuando aterrice el embedder real, `hybrid` será el default.

Detalle del primitive: [`primitives/query.md`](primitives/query.md).

---

## `rufino mcp-server`

```bash
rufino mcp-server --vault <PATH> [--no-rebuild]
```

Levanta el MCP server `ask-rufino` por stdio. Normalmente lo invoca Claude Code (registrado en `~/.claude.json` por el wizard / installer), no vos a mano.

Flags:

| Flag | Required | Default | Qué hace |
|---|---|---|---|
| `--vault PATH` | sí | — | Path al vault (debe existir) |
| `--rebuild` / `--no-rebuild` | no | `--rebuild` | Reconstruir índices semantic+graph al startup |

`--no-rebuild` es útil si tenés el vault muy grande y querés evitar el costo de rebuild en cada arranque del MCP — pero el primer arranque siempre necesita `--rebuild` para popular la DB.

El server queda corriendo hasta que se cierra el stdio (Claude Code lo maneja por vos).

Tools que expone: `search_vault`, `read_note`, `traverse_relations`, `list_persons`, `list_concepts`, `vault_info` (6+ tools — ver `src/rufino/mcp_server/tools.py`).

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
| 1 | Argumentos / spec / config inválido (input del usuario) |
| 2 | Feature deferida / wiring no implementado en v0.0.2 |
| 127 | Dependency externa faltante (`claude` CLI no encontrado, etc.) |
