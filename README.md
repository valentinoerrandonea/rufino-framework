# Rufino Framework

> Meta-arquitectura para construir tu propio sistema de gestión de conocimiento personal **conversando con Claude**, no programando.

Rufino Framework es una base reutilizable para armar **vaults de conocimiento** (estilo Obsidian) adaptados a tu vertical: notas de facultad, 1:1 con empleados, knowledge graph de proyectos, coaching financiero, lo que sea. La pieza distintiva es que **no escribís configs ni código**: corrés `rufino bootstrap`, Claude te entrevista en lenguaje natural, y al cerrar la conversación materializa toda la infraestructura del vault — estructura, prompts, ingestors, outputs, reglas de memoria, MCP server.

---

## Por qué existe

La mayoría de los sistemas de notas piden que **construyas tu sistema antes de usarlo**: definir databases, properties, relations, tags, taxonomy. Eso bloquea. La gente abandona Notion no por las features, abandona por el costo cognitivo de mantener el esquema vivo.

Rufino invierte el patrón: vos solo **capturás**; el sistema se organiza, enriquece y conecta solo, async, vía LLMs. La primera versión (`rufino-notes-and-memory`) implementó esa filosofía para un caso concreto — la memoria personal de Val. Funcionaba bien para ese caso, pero quedó **hardcodeada** a él.

**Rufino Framework lleva la misma filosofía un nivel más arriba:** ya no construís tu sistema de notas, pero tampoco construís tu *framework* de notas. Conversás con Claude, decís qué problema querés resolver, y el framework materializa el adapter set adecuado.

Lectura más larga sobre la filosofía y el paradigma A2P que la sustenta: [`docs/philosophy.md`](docs/philosophy.md).

---

## Cómo funciona

```
1.  ./install.sh                              # instala el CLI rufino en pipx
2.  rufino bootstrap                          # arranca el wizard conversacional
        ↓
    Claude te entrevista (en lenguaje natural, sin jerga técnica)
        ↓
    Confirma el resumen de qué va a armar
        ↓
    Big bang: materializa vault + adapters + MCP server + memory loop
        (transaccional — o sale todo, o nada)
3.  Listo: tirá notas al vault, conversá con Claude en cualquier proyecto,
    recibí los digests, consultá el vault desde el MCP `ask-rufino-<slug>`.
```

---

## Lo que recibís al final del bootstrap

- Un **vault de Obsidian** con la estructura adaptada a tu vertical (no un template — generado para tu caso puntual).
- **Adapters** generados que cubren las 6 primitives según lo que necesite tu vertical:
  - **Ingest** — traer data de fuentes externas (Drive, Calendar, GitHub, Spotify, etc.)
  - **Process** — augmentar notas crudas con frontmatter, triples, tags, wikilinks
  - **Output** — generar derivados (digests semanales, reportes mensuales, alertas)
  - **Memory loop** — guardar al vault lo que conversás con Claude Code
  - **Q&A loop** — preguntas que solo vos podés resolver (materia ambigua, persona nueva)
  - **Query** — API unificada de lectura (lexical + semántico + grafo)
- Un **MCP server `ask-rufino-<slug>`** (uno por vault) registrado en tu Claude Code, para consultarle al vault desde cualquier conversación. Varios vaults coexisten sin pisarse.
- **Opcional** (opt-in en el wizard): hooks + skill `/remember-<slug>` en `~/.claude/` para que el framework capture y analice tus conversaciones de Claude Code y guarde lo valioso al vault automáticamente.

---

## Verticales de ejemplo

Casos de uso donde el patrón Rufino aplica con un vault adaptado:

| Vertical | Qué resuelve |
|---|---|
| **Notas de facultad** | Capturar clases, papers, ideas; augmentar con concept extraction; digests por materia; year-in-review académico |
| **1:1 de empleados** | Tracking de conversaciones con cada reporte directo; bio mensual por persona; meeting prep automático |
| **Knowledge graph de proyectos** | Decisiones técnicas, postmortems, cross-project insights via embeddings; digests por equipo |
| **Coaching financiero** | Transacciones + contexto narrativo; categorización; bio mensual de hábitos; year-in-review financiero |
| **Memoria personal** | El caso original — chats, calendar, browsing, capturas en una sola memoria con grafo |

Más detalle en [`docs/use-cases.md`](docs/use-cases.md).

---

## Instalación

Requisitos:

- **macOS o Linux**
- **Python 3.11+** (verificalo con `python3 --version`)
- **[pipx](https://pipx.pypa.io/)** — `brew install pipx && pipx ensurepath` en macOS, o `python3 -m pip install --user pipx && python3 -m pipx ensurepath` en Linux
- **[Claude Code CLI](https://github.com/anthropics/claude-code)** instalado y autenticado (`claude --version`)
- Opcional pero recomendado: **`jq`** (`brew install jq`) — para registrar el MCP server automáticamente

Instalación:

```bash
git clone https://github.com/<owner>/rufino-framework.git ~/rufino-framework
cd ~/rufino-framework
./install.sh
```

El instalador:

1. Chequea que Python ≥ 3.11 y pipx estén disponibles
2. Instala el package en un venv aislado con `pipx install -e .` (PEP 668 safe)
3. Resuelve el bin dir de pipx y agrega `# rufino-framework` a tu shell rc si falta
4. Crea `~/.rufino/` con la estructura base (`state/`, `backups/`, `adapters/{ingest,process,output,memory_loop}/`)
5. Registra el MCP server `ask-rufino-<slug>` (slug = basename del vault) en `~/.claude.json` *si* exportaste `RUFINO_VAULT` apuntando a una carpeta existente; si no, el wizard lo registra al cierre del bootstrap

Al terminar imprime:

```
Listo. Para empezar, abrí una shell nueva (o source ~/.zshrc) y corré:
    rufino bootstrap
```

Si la instalación falla, ver [`docs/troubleshooting.md`](docs/troubleshooting.md).

---

## Quick start

Después de instalar:

```bash
rufino bootstrap
```

Arranca el wizard conversacional. Claude te va a preguntar cosas como:

> *¿Qué problema querés resolver?*
> *¿Qué te gustaría tener centralizado en un solo lugar?*
> *Cuando agregás algo nuevo, ¿qué te gustaría que pase?*
> *¿Qué resúmenes te servirían?*

Al cerrar, te muestra un resumen en lenguaje natural de qué va a armar (sin jerga técnica) y te pide confirmación. Si decís sí, materializa todo en una transacción (`vault + adapters + memory loop + MCP`). Si decís no, vuelve a iterar.

Lectura completa del flujo: [`docs/getting-started.md`](docs/getting-started.md). Cómo conduce Claude el wizard: [`docs/wizard.md`](docs/wizard.md).

---

## Comandos disponibles

Para ver flags completos: `rufino <cmd> --help`. Referencia detallada: [`docs/cli-reference.md`](docs/cli-reference.md).

| Comando | Para qué sirve |
|---|---|
| `rufino bootstrap [--dry-run]` | Arranca el wizard conversacional. `--dry-run` imprime el system prompt sin lanzar Claude |
| `rufino version` | Imprime la versión instalada |
| `rufino materialize --spec FILE --vault X --claude-home Y --state-dir Z` | Materializa un vault desde una `WizardSpec` JSON (lo que el wizard genera) |
| `rufino install-memory-loop <adapter_dir> --vault X --claude-home Y` | Instala un Memory loop adapter en `~/.claude/` |
| `rufino ingest <adapter_dir> --vault X --state-dir Y` | Corre un Ingest adapter una vez |
| `rufino process <note> --vault X --mode {light\|full\|lint}` | Procesa una nota. `full` single-note queda diferido — usá `process-batch` para procesar en lote |
| `rufino process-batch <zip-or-dir>` | Batch-procesa un corpus a notas augmentadas vía Claude workers (v0.1.0). Ver [`docs/cli-reference.md#rufino-process-batch`](docs/cli-reference.md#rufino-process-batch) |
| `rufino output <adapter_dir> --vault X` | Corre un Output adapter una vez |
| `rufino qa-poll --vault X --state-dir Y` | Procesa respuestas pendientes en `questions/` |
| `rufino query "..." --vault X --mode {lexical\|semantic\|hybrid}` | Busca en el vault. `semantic`/`hybrid` requieren embedder real (deferido) |
| `rufino mcp-server --vault X [--no-rebuild]` | Levanta el MCP server (registrado como `ask-rufino-<slug>` por vault) por stdio |

---

## Upgrade

```bash
cd ~/rufino-framework
git pull
./upgrade.sh
```

El upgrade:

1. Lee la versión instalada de `~/.rufino/version`
2. Compara con la del repo (declarada en `src/rufino/version.py`)
3. Si son distintas: hace backup de `~/.rufino/` en `~/.rufino/backups/<timestamp>/`, reinstala el package con `pipx reinstall`, corre las migrations pendientes de `migrations/` en orden lexicográfico
4. Si son iguales: imprime `Already at <version>. Nothing to do.`

Detalle, política de downgrades, y cómo escribir migrations: [`docs/upgrading.md`](docs/upgrading.md).

---

## Estado

**v0.1.0** — `rufino process-batch` orquesta `claude` headless en paralelo
para batch-procesar corpus enteros (ZIPs, carpetas mixtas con md/docx/pptx/pdf/txt),
con Q&A loop end-to-end (preguntas pendientes se reanudan vía `qa-poll`).
Algunas piezas siguen **deferidas a propósito** (no son bugs):

- `transform.py` (escape hatch de código determinista en adapters) — el manifest acepta el campo, el runner todavía no lo invoca
- `Ingest output_mode: emit_augmented` (streaming directo a Process) — manifest parsea, dispatcher no wireado
- Single-note `rufino process --mode full` — exits con código 2; usá `process-batch` para procesar en lote
- Embedder real (Ollama + `nomic-embed-text`) — actualmente hay un placeholder `_NoopEmbeddings` que tira `NotImplementedError`, por eso `--mode lexical` es el único totalmente operativo en `rufino query`

---

## Arquitectura — vista rápida

El framework provee **6 primitives** (Ingest, Process, Output, Query, Memory loop, Q&A loop) con contratos versionados. El wizard genera **adapters** específicos del vertical que cumplen esos contratos. Los adapters tienen **4 shapes** heterogéneos según la primitive (worker, service, vertical config, question template) — la heterogeneidad es intencional, no un accidente.

La abstracción load-bearing es el **transaction log** (`runtime/transaction_log.py`): cada operación que toca disco/keychain/launchd se registra con su inverso, y cualquier fallo durante materialización dispara rollback completo. Eso es lo que hace posible el "big bang" del bootstrap.

Vista de alto nivel para contribuidores: [`docs/architecture.md`](docs/architecture.md).

---

## Documentación

Índice completo en [`docs/README.md`](docs/README.md). Atajos:

**Para usar el framework:**
- [Filosofía](docs/philosophy.md) — qué es y por qué existe
- [Getting started](docs/getting-started.md) — primer bootstrap paso a paso
- [Conceptos](docs/concepts.md) — vocabulario (vault, adapter, primitive, etc.)
- [Casos de uso](docs/use-cases.md) — verticales target
- [El wizard](docs/wizard.md) — cómo conduce Claude la entrevista
- [CLI reference](docs/cli-reference.md) — cada comando y flag
- [Upgrading](docs/upgrading.md) — versionado y migrations
- [Troubleshooting](docs/troubleshooting.md) — problemas comunes

**Para contribuir / escribir adapters:**
- [Architecture](docs/architecture.md) — overview para desarrolladores
- [Writing adapters](docs/writing-adapters.md) — guía para autores de adapters
- [Runtime internals](docs/runtime.md) — transaction log, sandbox, scheduler, secrets
- [Primitives](docs/primitives/) — schema por primitive
- [Adapter shapes](docs/adapters/) — los 4 shapes en detalle

---

## Licencia

(TBD — definir cuando se cierre la decisión de distribución, ver `decisionDistribucionRepoPrivado` en el vault.)
