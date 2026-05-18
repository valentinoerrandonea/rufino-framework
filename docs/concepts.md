# Conceptos / glosario

Vocabulario que aparece en el resto de los docs.

## Vault

Carpeta del usuario donde viven sus notas en markdown. Compatible con Obsidian (frontmatter YAML + wikilinks). Cada usuario tiene **uno**; lo materializa el wizard durante el bootstrap.

Estructura típica:

```
<vault>/
├── perfil.md              # quién es el dueño, qué hace
├── README.md              # auto-generado por el wizard, en lenguaje user
├── inbox/                 # entrada cruda
├── <carpetas-vertical>/   # apuntes/, papers/, transacciones/, lo que sea
├── _meta/                 # indices, embeddings.sqlite, lint reports
└── questions/             # Q&A pendientes para el usuario
```

El vault es la **fuente de verdad**. Cualquier consulta o derivado lee de acá.

## Primitive

Componente core del framework con una responsabilidad bien definida. v0.0.2 tiene **6 primitives**:

| Primitive | Qué hace |
|---|---|
| **Ingest** | Trae data de fuentes externas (Drive, GitHub, Calendar, Spotify…) al vault |
| **Process** | Augmenta notas crudas (frontmatter, body, triples, tags, wikilinks) |
| **Output** | Genera derivados (digests, reportes, alertas) |
| **Query** | API unificada de lectura (lexical + semántica + grafo) |
| **Memory loop** | Integra con conversaciones de Claude Code (hooks, /remember, reglas) |
| **Q&A loop** | Pipeline de preguntas que solo el usuario puede contestar |

Detalle por primitive: [`primitives/`](primitives/).

## Adapter

Configuración específica del vertical que cumple el contrato de una primitive. El framework provee las primitives; el wizard genera los adapters.

Ejemplos:
- `ingest/drive-pdfs` — Ingest adapter que pulla PDFs de una carpeta de Drive
- `process/apunte-clase` — Process adapter que augmenta apuntes de clase
- `output/digest-semanal` — Output adapter que manda un resumen los viernes
- `memory_loop/facultad` — Memory loop adapter con las reglas del vertical facultad

Viven en `~/.rufino/adapters/<primitive>/<adapter_name>/`.

## Adapter shape

Los adapters no tienen todos la misma forma. Hay **4 shapes**, uno por familia de primitive:

| Shape | Primitives | Estructura |
|---|---|---|
| **Worker adapter** | Ingest, Process, Output | Carpeta con `manifest.yaml` + `prompt.md`/`template.md` + opcional `transform.py` |
| **Service primitive** | Query | API pura, no tiene adapter |
| **Vertical config** | Memory loop | Carpeta con `manifest.yaml` + `rules/*.md` |
| **Question template** | Q&A loop | Archivo único: markdown con frontmatter |

La heterogeneidad es intencional — ver [`philosophy.md` §6](philosophy.md#6-heterogeneidad-honesta).

Detalle: [`adapters/`](adapters/).

## Manifest

Archivo `manifest.yaml` declarativo dentro de cada adapter. Define el contrato del adapter con el framework: qué datos espera, qué destino tiene el output, qué triggers lo activan, qué triples puede usar, etc.

El framework valida cada manifest antes de instalarlo. Errores bloquean install; warnings loggean.

Schema por primitive en [`primitives/`](primitives/).

## Frontmatter

Bloque YAML al principio de cada nota markdown:

```markdown
---
type: apunte_clase
materia: ml-i
fecha_clase: 2026-05-16
profesor: mendez
tags: [materia/ml-i, tema/regresion-logistica, profesor/mendez]
triples:
  - { r: tema-de, o: ml-i }
  - { r: expuesto-por, o: profesor-mendez }
---

# Clase 3 — regresión logística

...
```

El frontmatter es **la API entre las primitives y el vault**: Process lo escribe, Query lo lee. El campo `triples:` es la fuente del grafo. Los `tags:` son el sistema de organización por ejes.

## Triple

Relación tipada entre dos notas, declarada en el frontmatter:

```yaml
triples:
  - { r: <relation>, o: <object> }
```

`r` es la **relación** (verbo) — del vocabulario declarado en el adapter Process que generó la nota. `o` es el **objeto** — slug de otra nota del vault.

Ejemplos:
- `{ r: tema-de, o: ml-i }` — este apunte tiene tema-de ml-i
- `{ r: expuesto-por, o: profesor-mendez }` — este apunte expuesto-por profesor-mendez
- `{ r: extiende, o: paper-attention-is-all-you-need }` — este paper extiende attention-is-all-you-need

El framework parsea los triples del frontmatter de todas las notas y los carga en un triple store SQLite. Query layer expone `traverse()` sobre ese grafo.

**El vocabulario es por-vertical.** El adapter Process declara qué relaciones puede usar (`triple_vocabulary: [...]`), y el LLM las usa al augmentar. No hay un vocabulario global del framework.

## Wikilink

Sintaxis `[[note-slug]]` o `[[note-slug|display text]]` dentro del body de una nota. Obsidian-compatible. El framework usa wikilinks para conexiones blandas (mencionar otra nota) y triples para conexiones tipadas (relación con verbo).

## Wizard

El componente conversacional que el usuario invoca con `rufino bootstrap`. Es un system prompt rico que Claude ejecuta como **agente entrevistador** — con una checklist interna de objetivos, reglas operativas de conversación, y catálogo de patterns.

El wizard no escribe código directo. Al cerrar el cumplimiento de la checklist, genera una `WizardSpec` (JSON) y la pasa a `rufino materialize`.

Detalle: [`wizard.md`](wizard.md).

## Pattern (del wizard)

Estructura abstracta y combinable que Claude reconoce durante la entrevista. Hay 6 iniciales:

| Pattern | Trigger language |
|---|---|
| `discrete_events_with_metadata` | "trackear", "registrar cada vez", números+fechas |
| `long_documents_extraction` | "mis apuntes", "papers", PDFs |
| `person_centric_tracking` | "personas", "1:1", "empleados" |
| `decision_log_with_rationale` | "ADRs", "por qué hicimos X" |
| `temporal_self_observation` | "cómo viene mi mes/año" |
| `knowledge_graph_projects` | "ideas conectadas", "vault Obsidian" |

Los patterns **no son verticales** — un vertical real combina 2-3. Ej: *facultad* = `long_documents_extraction` + `person_centric_tracking` (profesores).

Viven en `src/rufino/wizard/patterns/`.

## Big bang

El bootstrap es transaccional: o se aplica todo (vault + adapters + memory loop + MCP server registration + cron jobs), o nada. No hay saves intermedios. Si algo falla, el [transaction log](#transaction-log) ejecuta el rollback inverso.

Ver [`philosophy.md` §5](philosophy.md#5-big-bang).

## Transaction log

Abstracción load-bearing del framework. Cada operación que toca disco / keychain / launchd se registra **antes** de ejecutarse en un log JSON, junto con su inverso:

```json
[
  { "op": "mkdir", "path": "/Users/beto/facultad", "rollback": "rmdir" },
  { "op": "write", "path": ".../perfil.md", "rollback": "delete" },
  { "op": "keychain_add", "service": "rufino-belo-oauth", "rollback": "keychain_delete" },
  { "op": "plist_install", "name": "com.rufino.process-apunte", "rollback": "plist_uninstall" }
]
```

Si la operación completa sale bien → el log se guarda como auditoría. Si falla → se lee en reverso y cada `rollback` se ejecuta. Implementación en `src/rufino/runtime/transaction_log.py`.

Más en [`runtime.md`](runtime.md#transaction-log).

## Helper / helper API

Librería versionada (`src/rufino/helpers/v1/`) que el framework expone a los adapters. Provee primitives útiles: `query_vault`, `ask_user`, `keychain_secret`, `cursor_persist`, etc.

Versionada con semver. El framework mantiene compatibilidad **2 versiones** simultáneas. Cuando un adapter usa una versión vieja, se carga con deprecation warning.

## MCP server (`ask-rufino`)

Servidor MCP (Model Context Protocol) sobre stdio. Lo lanza `rufino mcp-server --vault <X>`. Expone 6+ tools al Claude Code anfitrión para consultar el vault: `search_vault`, `read_note`, `traverse_relations`, etc.

Se registra en `~/.claude.json` al cierre del bootstrap. Cualquier conversación de Claude Code en *cualquier* proyecto puede invocarlo.

Detalle: [`primitives/query.md`](primitives/query.md).

## Memory loop

La integración entre las conversaciones de Claude Code y el vault. Tiene tres ramas:

1. **Hooks** (`UserPromptSubmit`, `Stop`, `SessionStart`) que se instalan en `~/.claude/hooks/` — cargan reglas, detectan momentos para guardar.
2. **Skill `/remember`** — el mecanismo canónico de escritura al vault desde una conversación.
3. **Reglas globales** — markdown en `~/.claude/rules/common/<vertical>-rules.md` que se cargan al iniciar cada sesión.

El usuario nunca invoca esto a mano. Funciona transparente mientras conversa.

Detalle: [`primitives/memory-loop.md`](primitives/memory-loop.md).

## Q&A loop

Mecanismo para preguntas que **solo el usuario puede contestar** — típicamente porque hay ambigüedad que el LLM no debe resolver inventando.

Flow:
1. Adapter llama `api.ask_user(template_name, context, callback)` durante el processing
2. Framework crea `<vault>/questions/<YYYY-MM-DD>-<slug>.md` desde el template
3. Adapter caller queda en estado `awaiting_user_input`
4. Usuario edita el frontmatter `answer:` de la question
5. `rufino qa-poll` detecta answer llena → invoca callback → resume el adapter

Detalle: [`primitives/qa-loop.md`](primitives/qa-loop.md).

## Sandbox

(Deferido en v0.0.2.) Cuando `transform.py` se implemente, va a correr en un sandbox `subprocess.run` con timeout, env restringido, filesystem readonly excepto `transform_writes_to`, y network bloqueado por default. Implementación parcial en `src/rufino/runtime/sandbox.py`.

## `~/.rufino/`

Directorio raíz del state del framework (no del vault). Layout:

```
~/.rufino/
├── version                 # versión instalada (texto plano)
├── applied-migrations      # un filename por migration aplicada
├── state/                  # cursores de Ingest, dedup, qa state
├── backups/<timestamp>/    # snapshots pre-upgrade
└── adapters/{ingest,process,output,memory_loop}/<adapter_name>/
```

El vault del usuario es **independiente** de `~/.rufino/`. El framework escribe su propio state acá; el vault es del usuario.

## `WizardSpec`

JSON que el wizard genera al cerrar la entrevista y le pasa a `rufino materialize`. Define:
- Vertical name
- Patterns elegidos
- Entidades y vocabulario
- Adapters a generar (ingest, process, output, memory_loop)
- Q&A templates

Validado por `src/rufino/wizard/spec_schema.py` antes de materializar — si es inválido, materialize aborta con error.

Spec del schema en código: `validate_spec()` en `spec_schema.py`.

## Pattern de naming

- **Manifest adapters** en `~/.rufino/adapters/{ingest,process,output,memory_loop}/<adapter_name>/`. `adapter_name` es kebab-case.
- **Notas en el vault** usan slugs kebab-case. Frontmatter en YAML.
- **Slugs cross-referenciados** en triples y wikilinks deben coincidir (`{ r: tema-de, o: ml-i }` → existe `materias/ml-i.md` o se va a crear).
- **Convención de vault: camelCase para los archivos** — heredado del vault personal de Val. Los adapters generados por el wizard pueden seguir esa convención o ajustar al vertical (los adapters de facultad podrían preferir kebab-case porque las materias son slugs).

## Cursor (Ingest)

Punto desde el cual reanudar el próximo fetch. Cada Ingest adapter persiste su cursor en `~/.rufino/state/<source_name>/cursor.json`. El framework provee `cursor_persist(name)` como helper.

Importante: el cursor **NO avanza** si el run tuvo errores — eso garantiza idempotencia y retry limpio.

## Dedup

Mecanismo para que un Ingest no re-emita el mismo fact dos veces. Cada Ingest emit_fact declara `dedup_by: <field>` (típicamente `id`). El framework mantiene un set por adapter en `~/.rufino/state/<source_name>/seen.json`.
