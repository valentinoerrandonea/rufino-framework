<div align="center">

# Rufino Framework

**Un meta-framework para construir tu propio sistema de gestión de conocimiento personal _conversando con Claude_, no programando.**

<sub>El sistema se organiza, enriquece y conecta solo. Vos solo capturás.</sub>

[![version](https://img.shields.io/badge/version-0.2.1-1f6feb?style=flat-square)](src/rufino/version.py)
[![python](https://img.shields.io/badge/python-3.11%2B-1f6feb?style=flat-square)](pyproject.toml)
[![tests](https://img.shields.io/badge/tests-705_passing-2ea043?style=flat-square)](tests/)
[![platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux-blueviolet?style=flat-square)](#instalación)
[![license](https://img.shields.io/badge/license-TBD-8b949e?style=flat-square)](#licencia)

[Filosofía](docs/philosophy.md) · [Getting started](docs/getting-started.md) · [Verticales](docs/use-cases.md) · [CLI reference](docs/cli-reference.md) · [Architecture](docs/architecture.md)

</div>

---

## Por qué existe

> La mayoría de los sistemas de notas piden que **construyas tu sistema antes de usarlo**: definir databases, properties, relations, tags, taxonomy. Eso bloquea. La gente abandona Notion no por las features — abandona por el costo cognitivo de mantener el esquema vivo.

Rufino invierte el patrón:

- **Vos capturás.** Notas crudas, sin formato, donde sea.
- **El sistema se organiza solo.** Augmenta con frontmatter, triples, tags, wikilinks vía LLMs, en async.
- **Vos preguntás en lenguaje natural** y Claude consulta tu vault como si fuera memoria suya.

La primera versión (`rufino-notes-and-memory`) implementó esa filosofía para **un caso concreto** — la memoria personal de Val. Funcionaba bien, pero quedó hardcodeada.

**Rufino Framework lleva la misma filosofía un nivel más arriba:** ya no construís tu sistema de notas, pero tampoco construís tu *framework* de notas. Conversás con Claude, decís qué problema querés resolver, y el framework materializa el adapter set adecuado en una sola transacción (`vault + adapters + memory loop + MCP server`).

> Lectura completa de la filosofía y el paradigma **A2P (Assistant-Adapted Programs)** que la sustenta:
> **[`docs/philosophy.md`](docs/philosophy.md)**

---

## Cómo se siente

```
┌────────────────────────────────────────────────────────────────────────────┐
│  $ ./install.sh                                                            │
│  $ rufino bootstrap                                                        │
│                                                                            │
│      ─── (Claude arranca como wizard) ───                                  │
│      "Hola, vamos a armar tu sistema. ¿Qué problema querés resolver?"      │
│      ────────────────────────────────────                                  │
│           ↓                                                                │
│           conversación de 5-10 min, sin jerga técnica                      │
│           ↓                                                                │
│           Claude propone un resumen en lenguaje user                       │
│           ↓                                                                │
│           "¿Dale así, o algo no encaja?"                                   │
│           ↓                                                                │
│      ╔════════════════ big bang (transaccional) ════════════════╗          │
│      ║   vault/                                                 ║          │
│      ║     ├─ inbox/                                            ║          │
│      ║     ├─ <entities>/                                       ║          │
│      ║     └─ _meta/                                            ║          │
│      ║   adapters/{ingest,process,output,memory_loop}/...       ║          │
│      ║   ~/.claude.json  ←  ask-rufino-<slug> registrado        ║          │
│      ║   ~/.claude/hooks/  ←  memory loop (opt-in)              ║          │
│      ╚══════════════════════════════════════════════════════════╝          │
│                                                                            │
│  $ # listo. Tirá notas al vault, conversá con Claude desde cualquier       │
│  $ # proyecto, recibí los digests, consultá vía MCP `ask-rufino-<slug>`.   │
└────────────────────────────────────────────────────────────────────────────┘
```

Si algo falla en cualquier paso del big bang, el **TransactionLog** dispara rollback completo: vault no creado, plists desinstalados, keychain limpio. **O sale todo, o nada.**

---

## Lo que recibís al cerrar el wizard

<table>
<tr>
<td width="50%" valign="top">

#### Vault de Obsidian adaptado

Estructura **generada para tu caso**, no un template. Carpetas, frontmatter, vocabulario, triples y reglas de tagging que el wizard inventó conversando con vos.

</td>
<td width="50%" valign="top">

#### Adapters operativos

Implementaciones concretas de las 6 primitives (ver más abajo) que cubren tu vertical: cron schedules, prompts, templates, fetchers, hooks.

</td>
</tr>
<tr>
<td valign="top">

#### MCP server por vault

`ask-rufino-<slug>` registrado en `~/.claude.json`. Le preguntás a tu vault desde **cualquier** conversación con Claude Code. Varios vaults coexisten sin pisarse.

</td>
<td valign="top">

#### Memory loop opt-in

Hooks + skill `/remember-<slug>` en `~/.claude/` que capturan y analizan tus conversaciones de Claude Code y guardan lo valioso al vault — automáticamente, sin pedírselo cada vez.

</td>
</tr>
</table>

---

## Las 6 primitives

```
                   ┌──────────────────────────────────────┐
                   │              VAULT                   │
                   │   (markdown + frontmatter + triples) │
                   └──────────────────────────────────────┘
                                    ▲
                                    │
   ┌─────────────────────┬──────────┴──────────┬─────────────────────┐
   │                     │                     │                     │
   ▼                     ▼                     ▼                     ▼

 INGEST              PROCESS              OUTPUT               QUERY
 (worker)            (worker)             (worker)             (service)

 Trae data           Augmenta             Genera               API unificada
 externa             notas crudas         derivados            (lex+sem+graph)
 (Drive, API,        (frontmatter,        (digests,            con MCP server
 CSV, manual)        triples, tags,       reports,             por vault
                     wikilinks)           alertas)             (ask-rufino-X)

                                          ▲
                                          │
                                  ┌───────┴────────┐
                                  │                │
                                  ▼                ▼

                            MEMORY LOOP      Q&A LOOP
                            (vertical        (question
                             config)         template)

                            Captura          Pregunta sólo
                            convers. de      al user lo que
                            Claude Code      no se infiere
                            al vault         del contexto
                            (opt-in)
```

La heterogeneidad de **shapes** (worker / service / vertical config / question template) es **intencional**: forzar uniformidad romperia el modelo. Detalle: [`docs/architecture.md`](docs/architecture.md).

---

## Verticales de ejemplo

| Vertical | Qué resuelve |
| --- | --- |
| **Notas de facultad** | Capturar clases, papers, ideas; concept extraction; digests por materia; year-in-review académico |
| **1:1 de empleados** | Tracking de conversaciones con cada reporte directo; bio mensual por persona; meeting prep automático |
| **Knowledge graph de proyectos** | Decisiones técnicas, postmortems, cross-project insights vía embeddings; digests por equipo |
| **Coaching financiero** | Transacciones + contexto narrativo; categorización; bio mensual de hábitos; year-in-review financiero |
| **Memoria personal** | El caso original: chats, calendar, browsing, capturas en una sola memoria con grafo |

Más detalle en [`docs/use-cases.md`](docs/use-cases.md). Para escribir un vertical nuevo: [`docs/writing-adapters.md`](docs/writing-adapters.md).

---

## Instalación

<details>
<summary><b>Requisitos</b></summary>

- **macOS o Linux**
- **Python 3.11+** (`python3 --version`)
- **[pipx](https://pipx.pypa.io/)** — `brew install pipx && pipx ensurepath` (macOS) · `python3 -m pip install --user pipx && python3 -m pipx ensurepath` (Linux)
- **[Claude Code CLI](https://github.com/anthropics/claude-code)** instalado y autenticado (`claude --version`)
- Opcional: **`jq`** (`brew install jq`) — para registrar el MCP server automáticamente
- Opcional para embeddings: **[Ollama](https://ollama.com/)** + `ollama pull nomic-embed-text`

</details>

```bash
git clone https://github.com/valentinoerrandonea/rufino-framework.git ~/rufino-framework
cd ~/rufino-framework
./install.sh
```

El instalador:

1. Chequea Python ≥ 3.11 y pipx.
2. Instala el package con `pipx install -e .` (PEP 668 safe).
3. Resuelve el bin dir de pipx y agrega el path a tu shell rc si falta.
4. Crea `~/.rufino/` con la estructura base (`state/`, `backups/`, `adapters/`, `tx/`).
5. Registra el MCP server `ask-rufino-<slug>` en `~/.claude.json` si exportaste `RUFINO_VAULT`; si no, el wizard lo registra al cierre del bootstrap.

Si falla algo: [`docs/troubleshooting.md`](docs/troubleshooting.md).

---

## Quick start

```bash
rufino bootstrap
```

Claude te va a preguntar cosas como:

> *¿Qué problema querés resolver?*
> *¿Qué te gustaría tener centralizado en un solo lugar?*
> *Cuando agregás algo nuevo, ¿qué te gustaría que pase?*
> *¿Qué resúmenes te servirían?*

Al cerrar, te muestra un resumen en lenguaje natural de qué va a armar (sin jerga técnica) y te pide confirmación. Si decís **sí**, materializa todo en una transacción. Si decís **no**, vuelve a iterar.

Flujo completo: [`docs/getting-started.md`](docs/getting-started.md). Cómo conduce Claude el wizard: [`docs/wizard.md`](docs/wizard.md).

---

## Comandos disponibles

| Comando | Para qué sirve |
| --- | --- |
| `rufino bootstrap [--dry-run]` | Arranca el wizard conversacional. `--dry-run` imprime el system prompt sin lanzar Claude |
| `rufino version` | Imprime la versión instalada |
| `rufino materialize --spec FILE --vault X --claude-home Y --state-dir Z` | Materializa un vault desde una `WizardSpec` JSON |
| `rufino install-memory-loop <adapter_dir> --vault X --claude-home Y` | Instala un Memory loop adapter en `~/.claude/` |
| `rufino ingest <adapter_dir> --vault X --state-dir Y` | Corre un Ingest adapter una vez |
| `rufino install-ingest <adapter_dir> --vault X` | Materializa el cron a `launchd` (macOS) / `cron` (Linux) |
| `rufino list-ingests` · `uninstall-ingest <name>` | Listar / desinstalar jobs programados |
| `rufino process <note> --vault X --mode {light\|full\|lint}` | Procesa una nota (full delega a `run_batch(workers=1, batch_size=1)`) |
| `rufino process-batch <zip-or-dir>` | Batch-procesa un corpus a notas augmentadas vía Claude workers |
| `rufino output <adapter_dir> --vault X` | Corre un Output adapter una vez |
| `rufino qa-poll --vault X --state-dir Y` | Procesa respuestas pendientes en `questions/` |
| `rufino query "..." --vault X --mode {lexical\|semantic\|hybrid}` | Busca en el vault |
| `rufino detect-embeddings` | Chequea si Ollama + `nomic-embed-text` están listos |
| `rufino enable-embeddings --vault X [--state-dir Y]` | Activa el embedder semántico para un vault |
| `rufino disable-embeddings --vault X` | Vuelve `embeddings.enabled` a `false`. Idempotente |
| `rufino mcp-server --vault X [--no-rebuild]` | Levanta el MCP server (registrado como `ask-rufino-<slug>`) por stdio |

Referencia completa: [`docs/cli-reference.md`](docs/cli-reference.md).

---

## Upgrade

```bash
cd ~/rufino-framework
git pull
./upgrade.sh
```

El upgrade:

1. Lee la versión instalada en `~/.rufino/version`.
2. Compara con la del repo (`src/rufino/version.py`).
3. Si difieren: backup `~/.rufino/` a `~/.rufino/backups/<ts>/`, reinstala el package con pipx, corre las migrations pendientes de `migrations/` en orden lexicográfico.
4. Si son iguales: `Already at <version>. Nothing to do.`

Detalle, política de downgrades, escribir migrations: [`docs/upgrading.md`](docs/upgrading.md).

---

## Estado

> **v0.2.1** — release actual. 705 tests passing.

#### Operativo end-to-end (v0.2.0+)

- **Wizard conversacional** con system prompt rico, language rules, 6 patterns, checklist invisible y output esperado validado por `spec_schema`.
- **Big bang materialization** con TransactionLog (vault + adapters + MCP server + memory loop hooks opt-in, rollback completo en cualquier fallo).
- **6 primitives** wireadas: Ingest (3 output_modes: `import_raw` / `emit_facts` / `emit_augmented`), Process (light/full/lint), Output (digests + templates Jinja2), Query (lex/sem/hybrid con cross-encoder rerank), Memory loop (hooks + skill `/remember-<slug>`), Q&A loop (template + `qa-poll` resumption).
- **Embedder opt-in** con OllamaEmbedder + cross-encoder pin reproducible; cae a lexical si falla.
- **Scheduler real**: `launchd` en macOS, `cron` en Linux; `install-ingest` envuelto en TransactionLog.
- **Bounded I/O**: stdout/stderr de workers capeado streaming a 1 MB (no más OOM por runaway).
- **MCP server por vault**: stdio, registrado en `~/.claude.json`, varios vaults coexisten.

#### Diferido a v0.3+

- **Multi-hop graph traversal** (`depth > 1`). Forward + reverse a `depth=1` ya está.
- **File watcher para reindex automático** — actualmente se reconstruye vía `mcp-server --rebuild` o `enable-embeddings`.
- **Output adapters consumiendo queries semánticas** — el `_LexicalQueryAdapter` actual es solo léxico.
- **`sqlite-vec`** para acelerar coseno (hoy: `json.dumps(vec)` en TEXT + brute force).

---

## Arquitectura — en una imagen

```
  user input               wizard                materializer
  (conversación) ──→  ┌──────────────┐  ──→  ┌───────────────────────┐
                      │ system_prompt│       │ TransactionLog wraps  │
                      │ + Claude     │       │ every disk/keychain/  │
                      │ interactive  │       │ launchd op            │
                      └──────────────┘       │  ↓                    │
                              ↓              │  vault + adapters     │
                              └────WizardSpec│  + MCP server         │
                                  (validated)│  + memory loop hooks  │
                                             │  + cron jobs          │
                                             └───────────────────────┘
                                                       │
                                            success    │   any failure
                                              ┌────────┴────────┐
                                              ↓                 ↓
                                          ready to use     rollback() —
                                                            inverse op
                                                            for every
                                                            recorded
                                                            step, in
                                                            reverse order
```

Detalle: [`docs/architecture.md`](docs/architecture.md). Internals del runtime: [`docs/runtime.md`](docs/runtime.md).

---

## Documentación

<table>
<tr>
<td valign="top" width="50%">

#### Para usar el framework

- [Filosofía](docs/philosophy.md) — qué es y por qué existe
- [Getting started](docs/getting-started.md) — primer bootstrap
- [Conceptos](docs/concepts.md) — vocabulario base
- [Casos de uso](docs/use-cases.md) — verticales target
- [El wizard](docs/wizard.md) — cómo conduce Claude
- [CLI reference](docs/cli-reference.md) — cada comando
- [Upgrading](docs/upgrading.md) — versionado + migrations
- [Troubleshooting](docs/troubleshooting.md) — problemas comunes

</td>
<td valign="top" width="50%">

#### Para contribuir / escribir adapters

- [Architecture](docs/architecture.md) — overview para devs
- [Writing adapters](docs/writing-adapters.md) — guía
- [Runtime internals](docs/runtime.md) — tx log, sandbox, scheduler, secrets
- [Primitives](docs/primitives/) — schema por primitive
- [Adapter shapes](docs/adapters/) — los 4 shapes en detalle
- [Codereview history](docs/codereview/) — reviews por release
- [Plans](docs/superpowers/plans/) — planes de implementación

</td>
</tr>
</table>

---

## Licencia

TBD — definir cuando se cierre la decisión de distribución (ver `decisionDistribucionRepoPrivado` en el vault de Val).

---

<div align="center">
<sub>Construido con Claude Code · v0.2.1 · 2026</sub>
</div>
