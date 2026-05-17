# Rufino Framework — Design Spec

**Date:** 2026-05-16
**Status:** Design — pending review
**Author:** Val + Claude (brainstorming session)

---

## 1. Resumen ejecutivo

Rufino Framework es la evolución de `rufino-notes-and-memory` desde "memoria personal portable" hacia un **framework reutilizable** para construir vaults de conocimiento adaptados a cualquier vertical (notas de facultad, 1:1 de empleados, knowledge graph de proyectos, análisis financiero, etc.).

La pieza clave es un **wizard conversacional**: al instalar el framework, el user no escribe configs ni código — Claude lo entrevista en lenguaje natural sobre los objetivos del vault, y al cierre materializa toda la infraestructura adaptada (estructura, prompts, ingestors, outputs).

### Decisiones arquitectónicas principales

| Decisión | Elegida | Por qué |
|---|---|---|
| Variación entre vaults | C — primitives + adapters generados | Mismo motor mantenido + adapters específicos por vertical |
| Primitives core | 6 (Ingest, Process, Output, Query, Memory loop, Q&A) | Mínimo viable para cubrir los verticales target |
| Hooks de código | B — declarativo + transform.py opcional | Default revisable + escape hatch para lógica determinista |
| Shape de adapter | 4 shapes heterogéneos | Cada primitive tiene la forma que naturalmente le encaja |
| Modelo de wizard | Conversacional libre + greenfield + big bang | Máxima naturalidad + cero overhead de templates |
| Lenguaje del wizard | Objetivos del user, no componentes técnicos | "Qué querés trackear", no "qué entities configurar" |

---

## 2. Contexto y motivación

### 2.1 El punto de partida

Val tiene tres capas operativas hoy:

1. **`claudeSetup`** — su instancia personal de Rufino (privada, no distribuible)
2. **`rufino-notes-and-memory`** — versión portable v1 publicada el 2026-05-13 para terceros: clonan + ejecutan setup manual + obtienen un vault de Obsidian funcional con Rufino + las features de Fases 2-5 (9 ingestors externos, embeddings, MCP server, person resolver, digests, bio, year-review)
3. **`rufino-framework`** — el repo de este design doc, que arrancó como copia evolucionada de `rufino-notes-and-memory` pero todavía no está refactorizado al modelo framework

### 2.2 La conversación que disparó el pivot

Val recibió feedback de amigos sobre Rufino apuntando a casos de uso muy distintos al suyo:

- *"esto está buenísimo para dejarle todas mis notas de la facultad y tener todo centralizado"*
- *"esto está buenísimo para recopilar información sobre mis empleados para mejorar el feedback en 1:1"*
- Casos propios mencionados: knowledge graph de proyectos, análisis de transacciones de oiKO para coaching financiero

La conclusión: la propuesta de Rufino (capturar sin organizar manualmente + sistema que se construye solo después) es generalizable. Pero la implementación actual está hardcodeada al caso de Val.

### 2.3 La visión del framework (literal de Val, 2026-05-16)

> *"quiero que sea un framework en blanco. que al instalarlo (junto a claude code), claude te pueda realizar preguntas distintas sobre el caso de uso que le vas a dar, y que juntos vayan creando lo que seria la estructura de la boveda, y todo. me gustaria que el usuario defina su caso de uso, defina que es lo que quiere hacer, y claude code vaya guiando en las cosas que el usuario tiene que realizar para poder tener una boveda efectiva, y por sobre todo util."*

---

## 3. Filosofía y principios

### 3.1 Principios heredados de Rufino

Ver [rufinoFilosofia.md](../../proyectos/rufino/rufino-core/rufinoFilosofia.md) en el vault. Resumen:

- **Capturar sin organizar manualmente.** El usuario solo escribe; el sistema organiza, conecta y enriquece async.
- **No hay sistema que construir.** A diferencia de Notion, no hay paso de "configurar properties + databases + relations" antes de empezar.
- **El éxito se mide en captura, no en prolijidad.** El KPI es "¿escribiste esa idea de la 1am?", no "¿están todas las notas tageadas?".

### 3.2 Principios nuevos del framework

- **El sistema se diseña conversando, no programando.** El user habla con Claude sobre su vertical; Claude materializa la implementación.
- **Lenguaje de objetivos, no componentes.** Durante el wizard, no se mencionan manifests, adapters, primitives, triples. Se habla de "qué querés trackear", "qué te gustaría recibir", "cuando agregás algo qué pasa".
- **Greenfield siempre.** No hay templates por vertical. Cada vault es genuinamente del user.
- **Big bang.** El bootstrap es transaccional: o se materializa todo, o nada. Sin saves intermedios.
- **Heterogeneidad honesta.** No forzar uniformidad arquitectónica donde no aporta. Las primitives hacen cosas distintas; los adapters reflejan eso (4 shapes).

---

## 4. Arquitectura

### 4.1 Modelo de variación: opción C (primitives + adapters)

Tres opciones evaluadas:

| Opción | Cómo se ve | Por qué descartada (A, B) o elegida (C) |
|---|---|---|
| **A — Mismo motor, distinta config** | Scripts genéricos + configs YAML declarativas. Wizard solo escribe configs. | Bloquea verticales con lógica no-LLM (recomendaciones financieras requieren scoring numérico, no expresable en YAML). Val sería bottleneck para cada caso atípico. |
| **B — Núcleo mínimo + código a medida** | Framework provee convenciones; Claude genera scripts/prompts custom por vertical. | Cada vault es snowflake. `rufino upgrade` imposible (cada usuario tiene su código). Calidad inconsistente. Imposible compartir entre usuarios. |
| **C — Primitives + adapters generados** | Framework mantiene primitives reutilizables + contratos. Wizard genera adapters específicos del vertical que cumplen los contratos. | Mejor de ambos mundos: upgrades centrales + expresividad alta + adapters revisables. Modelo Rails generators / Helm chart + values / Obsidian core + plugins. |

**Elegido: C, arrancando como "B disciplinado".** Los adapters iniciales son scripts/prompts pegados al disco (cercano a B), pero el framework declara contratos explícitos desde día 1 + un validador chequea cada adapter al generarlo. Los patrones repetidos se refactorizan a primitives orgánicamente.

### 4.2 Las 6 primitives core

| Primitive | Qué hace | Shape adapter |
|---|---|---|
| **Ingest engine** | Trae data de fuentes externas y la normaliza | Worker adapter |
| **Process pipeline** | Augmenta notas crudas (frontmatter, body, triples, tags, wikilinks, indices) | Worker adapter |
| **Output dispatcher** | Genera derivados (digests, reportes, recomendaciones, alertas) | Worker adapter |
| **Query layer** | API unificada de lectura (lexical + semántica + grafo + facetada) | Service primitive (sin adapters) |
| **Memory loop** | Integración con conversaciones de Claude (hooks, /remember, reglas) | Vertical config |
| **Q&A loop** | Pipeline de preguntas que solo el user puede resolver | Question template |

Detalle de cada una en sección 5.

**Candidatas descartadas:** Vault schema (substrate, no código), Scheduler abstraction (plumbing), Person resolver (processor especializado), Validator de adapters (parte del wizard), Vault writer / git sync (helper común).

### 4.3 Los 4 shapes de adapter

| Shape | Primitives | Estructura |
|---|---|---|
| **Worker adapter** | Process, Ingest, Output | Carpeta + `manifest.yaml` + prompt/template + `transform.py` opcional |
| **Service primitive** | Query | API pura del framework, sin adapters |
| **Vertical config** | Memory loop | Carpeta + `manifest.yaml` + `rules/*.md` para Claude |
| **Question template** | Q&A loop | Markdown puro con frontmatter (no carpeta) |

Decisión: aceptar la heterogeneidad. Cada primitive tiene la shape que naturalmente le encaja. Forzar uniformidad genera ceremonia innecesaria (Q&A templates envueltos en carpetas vacías, Query con manifest declarativo de su API que es overkill).

### 4.4 Hooks de código: modelo B (híbrido)

El adapter es declarativo por default (`manifest.yaml` + `prompt.md`/`template.md`). Si la lógica requiere cálculo determinista no expresable en YAML/prompt, el adapter puede incluir un hook de código.

**Regla del wizard (cuándo generar hook):**

> *"Si tu lógica involucra cálculos determinísticos, montos, fechas, IDs o comparaciones numéricas → hook. Si no → declarativo."*

Durante la entrevista, Claude pregunta: *"¿necesitás hacer cálculos sobre los datos, o solo describirlos/clasificarlos?"*. Si la respuesta involucra números o reglas determinísticas, genera `transform.py`.

**v1 acotada a un solo hook:** `transform.py` con firma `transform(input_dict) → output_dict`, ejecutado después del LLM call si el manifest declara `transform_hook: ./transform.py`. v2+ podrá agregar `pre_process`, `post_process`, hooks bash si el wizard detecta necesidad.

**Mitigaciones de los contras:**

**Sandboxing (detalle):**

```python
subprocess.run(
    ["python3", adapter_path / "transform.py"],
    input=json.dumps(input_dict),
    timeout=60,                          # default; configurable hasta 300s
    capture_output=True,
    cwd=tmp_isolated_dir,
    env={"PATH": "/usr/bin", "PYTHONPATH": framework_helpers_v1},
    # Resource limits (Unix): RLIMIT_AS 512 MB, RLIMIT_CPU 30s
)
```

- **Filesystem:** readonly excepto path declarado en `transform_writes_to: ./output/` (relativo al cwd isolated)
- **Network:** bloqueado por default; opt-in con `transform_needs_network: true` en el manifest (loggea + requiere user OK al instalar)
- **Stdin/stdout:** JSON in, JSON out, sin acceso a TTY
- **Errores:** timeout = falla del adapter; non-zero exit = error reportado al user en lenguaje claro
- **Validador integrado:** el [validador del manifest (sección 4.5)](#45-validador-del-manifest) corre el hook con input dummy en el sandbox antes de instalar; si falla, bloquea install

**Versionado del helper API:** contratos versionados (`rufino_helpers/v1/`, `v2/`); adapter declara versión; framework mantiene compat 2 versiones; deprecation warnings al cargar adapter con versión vieja. Ver [sección 8.2](#82-versionado-del-helper-api).

### 4.5 Validador del manifest

Antes de instalar cualquier adapter, el framework corre un validador (uno por shape):

- **Schema YAML válido** del manifest
- **Required fields presentes** (varía por shape: worker / vertical config / question template)
- **Triple vocabulary** no usa keywords reservados (`type`, `id`, `created`, `updated`, `tags`)
- **Tag axes** sin overlap entre sí
- **Paths absolutos prohibidos** en `destination_path` (siempre relativos al vault)
- **Referencias a otros adapters** (ej: `process_with: <name>`) — el target existe
- **Si declara `transform_hook`**: archivo existe + es ejecutable + smoke test pasa en sandbox con input dummy
- **Si declara `template`**: archivo existe + placeholders válidos

**Comportamiento:**
- Errores **bloquean** instalación
- Warnings (ej: prompt sin `context_injectors`, adapter sin `qa_triggers` declarados) loggean pero permiten install
- Reportes en lenguaje claro con line number + sugerencia de fix

**Implementación:** módulo `validators/` con un validador por shape (`worker_validator.py`, `vertical_config_validator.py`, `question_template_validator.py`).

### 4.6 Rollback transaccional del bootstrap

La materialización del bootstrap es **transaccional** — o se aplica todo, o nada. Cada acción se loggea ANTES de ejecutarse en `~/.rufino/bootstrap-tx-<uuid>.json`:

```json
[
  { "op": "mkdir", "path": "/Users/beto/facultad", "rollback": "rmdir" },
  { "op": "write", "path": ".../perfil.md", "rollback": "delete" },
  { "op": "keychain_add", "service": "rufino-belo-oauth", "rollback": "keychain_delete" },
  { "op": "plist_install", "name": "com.rufino.process-apunte", "rollback": "launchctl_unload+rm" }
]
```

**Si bootstrap OK:** log se mueve a `~/.rufino/bootstrap-history/<vertical>-<date>.json` (referencia + auditoría).

**Si falla en cualquier paso:** log se lee en orden inverso, cada `rollback` se ejecuta.

**Edge case OAuth grants:** el rollback borra el entry del Keychain, pero el grant del lado del proveedor queda. Se asume aceptable + se documenta al user (*"podés revocar manualmente desde [link al provider]"*).

**Implementación:** módulo `runtime/transaction_log/` que envuelve cada operación con la registración pre-ejecución.

---

## 5. Las 6 primitives

### 5.1 Ingest engine

**API del framework:**

```
ingest(adapter_name?) → run_result
```

Helpers expuestos al adapter: `oauth_flow`, `keychain_secret(name)`, `cursor_persist(name)`, `dedup_check(slug)`, `fact_validate(schema)`. Scheduler integrado (materializa cadencia a launchd/cron/systemd según SO).

**3 output modes:**

| Mode | Output | Pasa por Process? | Ejemplo |
|---|---|---|---|
| `emit_fact` | Records atómicos estructurados en `<source>/facts/<slug>.md` | No | Commits de GitHub, plays de Spotify, transacciones bancarias |
| `import_raw` | Docs largos sin estructura en `rufino/inbox/` | Sí — invoca Process adapter declarado en `process_with` | PDFs de apuntes, papers, contratos |
| `emit_augmented` | Streaming directo a Process sin paso intermedio en disco | Sí (integrado) | Transcripts en vivo, scrapes que solo importan augmentados |

**Default trigger ingest → process:** `immediate` cuando `output_mode = import_raw` (decisión de Val: "push inmediato"). El adapter puede override a `defer` si prefiere batch.

**Adapter ejemplo (vertical finanzas, `ingest-belo`):**

```yaml
adapter_name: belo
source_name: belo
schedule: "*/30 * * * *"
auth:
  type: oauth2
  keychain_service: rufino-belo-oauth
  refresh_endpoint: https://api.belo.app/oauth/refresh

output_mode: emit_fact
emits: [transaccion]

fact_schema:
  id: string
  monto: number
  moneda: enum[ARS, USD, USDT]
  fecha: datetime
  cuenta: string
  contraparte: string

destination:
  facts: belo/facts/<YYYY-MM-DD>-<id>.md
  raw: belo/raw/<id>.json
dedup_by: id
```

**Flujo:** scheduler dispara → tokens del Keychain (refresh si expiró) → API call desde cursor → valida schema/dedup → escribe facts+raw → persiste cursor.

### 5.2 Process pipeline

**API del framework:**

```
process(note_path, mode="full" | "light" | "lint") → result
```

Pipeline interno fijo:
1. **Load adapter** — por `note_type` del frontmatter o inferencia desde carpeta/pattern
2. **Pre-process** — extracción de texto (PDF, DOCX, etc.), parsing si es estructurado
3. **Context injection** — corre `context_injectors` declarados, llama Query layer
4. **Render prompt** — sustituye `${placeholders}` en `prompt.md`
5. **LLM call** — sonnet default, overrideable por adapter
6. **Validate output** — chequea `output_schema` y `triple_vocabulary`
7. **Transform hook** — si declarado, corre `transform.py` en sandbox
8. **Q&A check** — si el LLM llamó `ask_user(...)` → dispara primitive Q&A
9. **Update indices** — `_index`, `_tags`, `_people`, promote concepts
10. **File move** — a `destination_path` con frontmatter completo
11. **Notify Output dispatcher** — triggers `on_new(<note_type>)`

**Modos:**
- `full` — pipeline completo (todos los pasos)
- `light` — solo pasos 9-10 (update indices + file move). Sin LLM, sin transform hook, sin Q&A. Útil para notas que el user/Claude escribió a mano y solo necesitan ser registradas + linkeadas
- `lint` — valida sin modificar (chequea triple_vocab, frontmatter schema, wikilinks rotos, etc.)

**Adapter ejemplo (vertical facultad, `process-apunte-clase`):**

`manifest.yaml`:

```yaml
adapter_name: apunte-clase
note_type: apunte_clase

applies_when:
  source_dir: rufino/inbox/
  matches_pattern: ["*.pdf", "*.md", "*.txt"]

llm: sonnet
mode_default: full

output_schema:
  required:
    materia: { type: enum_dynamic, source: "tags: materia/" }
    fecha_clase: date
    topics: list[str]
  optional:
    profesor: persona_ref
    bibliografia: list[ref]

triple_vocabulary:
  - tema-de         # apunte tema-de materia
  - expuesto-por    # apunte expuesto-por profesor
  - extiende        # apunte extiende apunte_previo
  - referencia      # apunte referencia bibliografia

tag_axes:
  - { axis: materia,  format: "materia/<slug>",  required: true }
  - { axis: tema,     format: "tema/<slug>",     min: 1 }
  - { axis: profesor, format: "profesor/<slug>", required: false }
  - { axis: concepto, format: "concepto/<slug>", min: 0 }

destination_path: "apuntes/{materia}/{fecha_clase}-{slug}.md"

qa_triggers:
  - { name: materia_ambigua, condition: "match_count(materia) >= 2" }
  - { name: tema_nuevo,       condition: "any(topic) not in known_topics(materia)" }

context_injectors:
  - { name: apuntes_previos,    query: "tag=materia/<materia>, last 10 by date" }
  - { name: bibliografia_known, query: "type=bibliografia, materia=<materia>" }
  - { name: profesores_known,   query: "persons with tag profesor/" }
```

`prompt.md` (esqueleto):

```markdown
Procesá este apunte de clase. Producí la versión augmentada siguiendo el output_schema declarado.

## Apunte crudo
${note_body}

## Contexto inyectado
- Apuntes previos de la materia: ${context.apuntes_previos}
- Bibliografía conocida: ${context.bibliografia_known}
- Profesores conocidos: ${context.profesores_known}

## Vocabulario de triples
${triple_vocabulary}

## Reglas
- Si la materia matchea 2+ candidatas → no inventes, llamá `ask_user(materia_ambigua)`.
- Si detectás topic nuevo → registralo y llamá `ask_user(tema_nuevo)` para confirmar nombre canónico.
- Triples solo del vocabulario declarado.

## Output
Markdown con frontmatter completo + body augmentado: resumen 3-5 bullets + desarrollo por subtopics + wikilinks a apuntes previos.
```

### 5.3 Output dispatcher

**API del framework:**

```
output(adapter_name?) → emit_result
```

Helpers: `query_vault`, `render_template`, `deliver(channel, content, meta)`.

**Channels built-in:** `file://`, `email://` (SMTP + Keychain), `webhook://`, `push://`.

**Triggers:** `cron` (cadencia) o `on_event` (subscripción a eventos del Process).

**Adapter ejemplo (vertical 1:1 empleados, `output-meeting-prep`):**

```yaml
adapter_name: meeting-prep
trigger:
  type: on_event
  event: calendar_event
  filter: "tag = '1:1' AND starts_in_hours < 24"

query:
  - { name: notas_persona,      expression: "tag=persona/<event.attendee> AND created >= last_1on1(<event.attendee>)" }
  - { name: feedback_pendiente, expression: "type=feedback AND target=persona/<event.attendee> AND status=pending" }
  - { name: okrs_persona,       expression: "type=okr AND owner=persona/<event.attendee> AND active=true" }

template: ./templates/meeting-prep.md

delivery:
  - { channel: file,  path: "meetings/<event.attendee>/<YYYY-MM-DD>-1on1.md" }
  - { channel: email, to: "manager@empresa.com", subject: "1:1 prep: <event.attendee>" }
```

### 5.4 Query layer

**API del framework (servicio puro, sin adapters):**

```python
search(query: str, mode: "lexical" | "semantic" | "hybrid") → [note_ref]
traverse(node: note_ref, relation: str, depth: int) → [note_ref]
filter(predicate: dict) → [note_ref]
embed(text: str) → vector
nearest(vector, k: int) → [note_ref]
get(note_ref) → note
```

**Backends:**
- **Lexical:** ripgrep sobre los markdown
- **Semántica:** embeddings DB (Ollama + sqlite-vec, reindexada por file watcher)
- **Grafo:** triple store SQLite parseado del frontmatter `triples:`
- **Facetada:** predicado declarativo sobre frontmatter fields

**Consumers (no adapters):**
- MCP server `ask-rufino` (Claude conversacional, ≥6 tools)
- CLI `rufino query "..." --mode hybrid`
- Output adapters via `query_vault` helper
- Wizard inicial (chequear si user ya tiene algo similar al adapter a generar)

### 5.5 Memory loop

**API del framework:**
- **Hook init** (al iniciar sesión Claude Code): carga `perfil.md` + `preferencias.md` + overview del proyecto (detectado por CWD)
- **Hook stop** (al cerrar sesión): ejecuta check de "¿hay algo para guardar al vault?"
- **Skill `/remember`** parametrizable: mecanismo canónico de escritura, decide carpeta destino según `note_type`
- **Reglas globales**: cargadas en cada sesión (`rules/common/*.md`)

**Adapter ejemplo (vertical facultad, `memory-loop-facultad`):**

```yaml
adapter_name: memory-loop-facultad
vertical_name: facultad

entity_types: [apunte_clase, materia, profesor, paper, tp, examen]

note_destinations:
  apunte_clase: "apuntes/<materia>/<YYYY-MM-DD>-<slug>.md"
  paper: "papers/<materia>/<slug>.md"
  tp: "tps/<materia>/<YYYY-MM-DD>-<slug>.md"
  examen: "examenes/<materia>/<YYYY-MM-DD>-<tipo>.md"

rule_extensions:
  - ./rules/facultad-vocabulary.md   # entidades + tags canónicos
  - ./rules/facultad-conventions.md  # cuándo crear qué tipo de nota
```

**Flujo (sesión típica):** user abre Claude Code en `~/facultad/` → hook init carga perfil + reglas adaptadas → user dice "el profe Méndez dio una clase sobre redes bayesianas" → Claude detecta nueva mención `[[profesor-mendez]]` (no existe) + concepto `redes-bayesianas` → propone guardar via /remember → escribe `apuntes/<materia>/<fecha>-clase-redes-bayesianas.md` + crea `profesores/mendez.md` con triple `dicta → <materia>` → hook stop al cierre pregunta si hay más.

### 5.6 Q&A loop

**API del framework:**

```python
ask_user(template_name, context: dict, options: list[str] | None) → question_id
get_answer(question_id) → answer | None
on_answer(question_id, callback) → None
```

Cuando un processor invoca `ask_user(...)`:
1. Framework crea `questions/<YYYY-MM-DD>-<slug>.md` desde el template indicado
2. Marca al adapter caller como `blocked` (nota con `status: awaiting_user_input`)
3. Espera. User contesta editando frontmatter `answer:`
4. Worker (file watcher o cron) detecta answer lleno → invoca callback registrado
5. Worker resume al adapter caller (mergea answer + completa lo que faltaba)

**Template ejemplo (`materia-ambigua` para vertical facultad):**

```yaml
---
template_name: materia_ambigua
required_context: [apunte_slug, candidate_materias, evidence]
expected_answer: "enum_from(candidate_materias) | 'nueva' | 'ninguna'"
---

# ¿De qué materia es este apunte?

Encontré candidatos:
{{#each candidate_materias}}
- **[[materia-{{this.slug}}]]** ({{this.confidence}}% — {{this.reason}})
{{/each}}

## Evidencia
{{evidence}}

## Respondé editando frontmatter
`answer: <slug>` | `answer: nueva` + `nueva_materia: <slug>` | `answer: ninguna`
```

---

## 6. El wizard conversacional

### 6.1 Modelo de interacción: conversacional libre

El wizard no sigue fases ordenadas con preguntas pre-escritas. Es una skill que declara los **objetivos finales** y Claude conversa libre persiguiendo esos objetivos con criterio propio.

**Implicación:** requiere tracking de estado interno (qué objetivos cumplió Claude, qué falta) + validador formal al cierre. Calidad depende del juicio de Claude — alto pero variable.

### 6.2 Diccionario interno (enfoque c: primitives + patterns)

El "diccionario" es el **system prompt rico del wizard**. Contiene:

**Skeleton de 11 secciones:**

1. Identidad y rol del wizard
2. Lenguaje user-facing (palabras prohibidas + traducciones mentales)
3. Conocimiento del runtime (primitives, shapes, transformers, channels)
4. Patterns iniciales (4-6)
5. Reglas de traducción lenguaje user → pattern
6. Reglas operativas (cómo conducir conversación) — ver [sección 6.9](#69-reglas-operativas-del-wizard-sección-6-del-system-prompt)
7. Tracking de objetivos (checklist invisible)
8. Output esperado (estructura de adapters a generar)
9. Features distintivas a comunicar siempre (memory loop, augmentation, triples, MCP)
10. Features opcionales según vertical (concept promotion, person resolver, embeddings, outputs)
11. Reglas de presentación del big bang (traducciones técnico→user de cada feature activada)

### 6.3 Patterns de composición (6 iniciales)

Los patterns son **abstractos y combinables** — un vertical real puede usar 2-3 mezclados. NO son verticales fijos.

| Pattern | Trigger language (señales del user) | Combinación de primitives |
|---|---|---|
| `discrete_events_with_metadata` | "trackear", "registrar cada vez", "saber cuánto", números+fechas | Ingest emit_fact + Process opcional + Output digest |
| `long_documents_extraction` | "mis apuntes/lecturas/papers", PDFs | Ingest import_raw + Process augmentation + embeddings |
| `person_centric_tracking` | "personas/contactos/empleados", "1:1" | Memory loop persona-central + Q&A dedup + Output meeting-prep |
| `decision_log_with_rationale` | "ADRs", "por qué hicimos X" | Process triple supersedes + lint orphans + Output search |
| `temporal_self_observation` | "cómo viene mi semana/mes/año" | Múltiples Ingest + Output bio + year-review |
| `knowledge_graph_projects` | "ideas conectadas", "vault tipo Obsidian" | Memory loop proyecto-central + Process triples ricos + Query grafo |

**Ejemplos de combinación:**
- **Coaching financiero (oiKO):** `discrete_events_with_metadata` + `temporal_self_observation` + `decision_log_with_rationale`
- **Facultad:** `long_documents_extraction` + `person_centric_tracking` (profesores)
- **1:1 empleados:** `person_centric_tracking` core + `decision_log_with_rationale` (feedback formal)

**Fallback si no encaja:** después de 2-3 preguntas sin matching pattern, Claude construye desde primitives básicas como modo b del diccionario.

### 6.4 Reglas de lenguaje user-facing

**Palabras prohibidas al hablar con el user:**

```
manifest, adapter, primitive, frontmatter, triple, schema, vocabulary,
ingest, output_mode, transform.py, output dispatcher, query layer,
memory loop, Q&A loop, MCP, RAG, embedding, augmentation, slug
```

**Traducciones mentales (decir → en vez de):**

| Lenguaje user (sí) | Lenguaje técnico (no) |
|---|---|
| "qué querés trackear" | "qué entidades vas a registrar" |
| "de dónde vienen tus datos" | "qué fuentes vas a configurar" |
| "cómo querés que se organicen" | "qué taxonomía / tags" |
| "qué resúmenes te servirían" | "qué outputs vas a generar" |
| "cuando agregás algo, qué pasa" | "qué process adapter dispatcher" |
| "armemos tu sistema" | "voy a generar los adapters" |

### 6.5 Cómo se invoca el wizard

Tres entrypoints combinados:

| Trigger | Para qué sirve |
|---|---|
| **CLI `rufino bootstrap`** | First-run post-install (default path). El instalador lo invoca automáticamente. |
| **Auto-detect** | Regla global de Claude Code: si abre sesión en dir con framework instalado pero vault vacío → propone *"¿arrancamos a armar tu sistema?"* |
| **Slash command `/init-rufino`** | Invocable manual para re-bootstrap o agregar adapters después |

### 6.6 Tracking de estado interno (checklist invisible)

El system prompt incluye una checklist con objetivos a cubrir antes del big bang:

```
☐ Vertical identificado
☐ Patrón(es) seleccionado(s) del catálogo
☐ Entidades centrales definidas
☐ Fuentes identificadas
☐ Política de processing (qué pasa cuando llega algo nuevo)
☐ Outputs definidos
☐ Vocabulary del vertical
☐ User confirmó el sistema a armar
```

Claude lee la checklist constantemente como referencia interna y la va marcando mentalmente. **No se muestra al user** (violaría regla de lenguaje no-técnico).

Validador formal al cierre chequea cumplimiento antes del big bang. Si falta algo, Claude pregunta más en lenguaje natural.

**Sin persistencia** — alineado con big bang sin resume.

### 6.7 Big bang final

**Plantilla del resumen al user (ejemplo vertical facultad):**

```
OK, te resumo lo que vamos a armar:

📒 Tu vault va a tener:
  - Apuntes organizados por materia
  - Papers archivados por área
  - Profesores como contactos
  - Conceptos clave (regresión, redes bayesianas, etc.) con su propia página
    cuando aparezcan seguido

🔌 Va a conectarse con:
  - Tu carpeta de Drive donde tirás PDFs
  - Tu calendario (para detectar fechas de examen)

⚡ Cuando agregues algo nuevo (PDF, nota, lo que sea):
  - Lo organiza por materia automáticamente
  - Lo enriquece (resumen, contexto, ideas conectadas)
  - Detecta los temas principales y los conecta con apuntes previos vía links
  - Si menciona un profe nuevo, lo registra como contacto
  - Si no está seguro de algo (de qué materia es, etc.), te pregunta —
    no inventa

💬 Mientras conversás conmigo en Claude Code:
  - Voy guardando lo valioso al vault sin que te acuerdes
  - Al cerrar la sesión te pregunto si hay más para guardar

🔍 Para encontrar cosas después:
  - Le preguntás al vault en lenguaje natural
    ("qué dijo el profe Méndez sobre redes bayesianas")
  - O navegás las conexiones como grafo

🤖 Desde cualquier conversación con Claude Code (incluso fuera del vault):
  - Le preguntás a Claude sobre tu vault y te contesta
    (ej: estás laburando en otro proyecto y querés saber qué viste sobre X
    en la cursada — preguntás directo, sin abrir el vault)

📬 Vas a recibir:
  - Resumen los viernes con lo que viste esa semana
  - Aviso 24h antes de cada examen
  - Tu "bio académica" del mes (qué materias avanzaste, qué temas estudiaste)

¿Dale así, o algo no encaja?
```

**Si user confirma:**
1. Materialización transaccional silenciosa (sin mostrar paths/manifests/adapters)
2. Dry-run silencioso (cada adapter una vez con input dummy)
3. OK: *"Listo, tu sistema está armado. Tirá un PDF a `~/facultad/inbox/` para probarlo."*
4. Falla: error user-friendly + *"¿lo arreglo y reintento, o lo discutimos juntos?"*

**Si user dice no encaja:** Claude pregunta qué cambiar y vuelve al loop conversacional (la checklist se desmarca lo necesario).

### 6.8 Política de interrupción

| Escenario | Comportamiento |
|---|---|
| User cierra a mitad | Cero side effects. Vault queda vacío. |
| User vuelve | Auto-detect ofrece *"tu bootstrap quedó sin terminar. ¿Lo retomamos desde cero o lo dejamos para otro día?"* |
| User dice *"para, no quiero seguir"* | Claude para limpio. *"OK, cuando quieras retomamos con `rufino bootstrap`."* |
| Dry-run falla y user cierra | Materialización rollback automático. Vault vuelve al estado pre-confirmación. |

### 6.9 Reglas operativas del wizard (sección 6 del system prompt)

7 heurísticas concretas que Claude aplica durante la conversación:

1. **Cerrar línea cuando hay suficiente** — si Claude tiene info para llenar el campo del checklist, parar de preguntar sobre ese tema. No over-engineer.
2. **Repreguntar con opciones concretas si la respuesta es ambigua** — no más open questions seguidas. *"¿es más A o más B?"* en vez de *"¿podés ser más específico?"*.
3. **Dar ejemplos cuando el user dice "no sé"** — concretos del vertical inferido, no genéricos.
4. **Tono colaborativo** — *"vamos a armarlo juntos"*, *"contame más"*. No inquisitorial.
5. **Invocar Query layer al inicio** — chequear si el vault ya tiene algo (debería estar vacío en bootstrap; si no, el wizard alerta).
6. **Cerrar el wizard solo cuando checklist completo + validador formal pasa** — no antes, aunque el user diga *"ya está, dale"*.
7. **Si user dice "para"** — parar limpio sin protestar, sin guardar nada, sin acusar.

### 6.10 Prereqs check del sistema

Antes de proponer cualquier feature opcional, el wizard chequea sus pre-requisitos vía catalog declarativo en `runtime/prereq_checker/`:

| Feature | Pre-requisitos |
|---|---|
| Embeddings | Ollama instalado + `nomic-embed-text` pulled |
| Secrets (todos los ingestors con OAuth) | `security` CLI (macOS) / Secret Service (Linux) |
| Algunos ingestors macOS (calendar, screentime) | Full Disk Access para `/bin/bash` |
| WhatsApp ingestor | Node instalado |
| Transform hooks | Python 3.11+ |
| GitHub ingestor | `gh` CLI autenticado |

Si falta un prereq y el wizard quiere proponer el feature:
- *"Para esta feature necesito que tengás X instalado. ¿Lo instalo ahora?"*
- *"¿La salteo por ahora y la activamos después?"*

Cada feature opcional declara sus prereqs en el catalog. El wizard NUNCA propone una feature cuyos prereqs no estén disponibles + sin opción de instalar.

### 6.11 Documentación generada post-bootstrap

Al cierre del bootstrap, el framework auto-genera `README.md` en la raíz del vault del user, en lenguaje user (no técnico).

**Secciones (derivadas del checklist + features activadas):**

```markdown
# Tu vault Rufino (vertical: <vertical>)

## Qué tenés acá
[descripción de las carpetas en lenguaje user — equivalente al big bang]

## Cómo agregar cosas
[instrucciones de agregar PDFs, notas a mano, configurar fuentes adicionales]

## Cómo encontrar cosas
[buscar en lenguaje natural via MCP / CLI, navegar conexiones]

## Si algo no funciona
[troubleshooting básico: cron no corre, OAuth expiró, etc.]

## Si querés cambiar el sistema
[invocar /init-rufino para agregar adapters, editar manualmente, etc.]
```

Una versión por vertical (customizada según las decisiones del wizard). Se actualiza cuando el user agrega/quita adapters via `/init-rufino`.

**Implicación técnica:** la materialización es **transaccional** — o se aplica todo (incluido dry-run OK) o nada. Si falla en cualquier paso, rollback. Implementación detallada en [sección 4.6](#46-rollback-transaccional-del-bootstrap).

---

## 7. Features distintivas (obligatorias vs opcionales)

### 7.1 Obligatorias (siempre activas — definen Rufino)

| Feature | Lenguaje user |
|---|---|
| **Memory loop** | *"Mientras conversás conmigo, voy guardando lo valioso al vault; al cerrar la sesión te pregunto si hay más"* |
| **Augmentation** | *"Cuando guardás algo crudo, lo organiza y enriquece (resumen, contexto, conexiones)"* |
| **Triples / grafo tipado** | *"Las notas se conectan entre sí mostrando relaciones (este paper extiende aquel, este profe dicta tal materia)"* |
| **MCP server `ask-rufino`** | *"Le preguntás a Claude sobre tu vault desde cualquier conversación, no solo cuando estás adentro del vault"* |

### 7.2 Opcionales (el wizard activa según vertical)

| Feature | Cuándo activar | Lenguaje user |
|---|---|---|
| **Concept promotion** | Patterns con conceptos emergentes (`long_documents_extraction`, `knowledge_graph_projects`) | *"Cuando un tema aparece varias veces, le crea una página dedicada automáticamente"* |
| **Person resolver** | Patterns con persona central (`person_centric_tracking`) | *"Si mencionás una persona nueva, la registra como contacto automáticamente"* |
| **Embeddings semánticos** | Siempre útil cuando vault > ~50 notas; default ON | *"Podés preguntarle al vault en lenguaje natural"* |
| **Outputs** (digest, bio, year-review) | Según pattern (`temporal_self_observation` activa todos) | *"Recibís resumen semanal / bio mensual / retrospectiva anual"* |

---

## 8. Stack runtime

### 8.1 Componentes

- **Runtime conversacional:** Claude Code CLI (`claude -p`)
- **Storage del vault:** Filesystem + Obsidian-compatible (markdown + frontmatter)
- **Scheduler:** launchd (macOS) / cron (Linux) / systemd (Linux) — abstracción del adapter (`schedule:` declarativo) materializada por el framework según OS
- **Lenguajes del adapter:** Markdown (manifests + prompts + templates) + Python opcional (transform.py)
- **Helpers de Process / Output:** Python (librería `rufino_helpers/`)
- **Storage de embeddings:** SQLite + sqlite-vec (Ollama + `nomic-embed-text` local)
- **Triple store:** SQLite (parseado del frontmatter `triples:` de cada nota)
- **Secrets:** macOS Keychain (`security` CLI) / Secret Service (Linux) — abstracción del framework
- **MCP server:** stdio local, expone 6+ tools al Claude Code anfitrión

### 8.2 Versionado del helper API

```
helpers/
├── v1/
│   ├── llm_call.py
│   ├── query_vault.py
│   ├── ask_user.py
│   └── ...
├── v2/
└── ...
```

- Adapter declara `helper_version: 1` en el manifest
- semver para breaking changes
- Compat: framework mantiene **2 versiones** simultáneas
- Deprecation warnings al cargar adapter con versión vieja (log + advertencia al user vía wizard cuando hace `rufino upgrade`)
- Migration scripts: `rufino upgrade-adapters --to v2` (opcional, dispara prompt al user)

### 8.3 Layout del repo

```
rufino-framework/
├── README.md, install.sh, upgrade.sh       # entrypoints user
├── cli/rufino                               # CLI binary (bash thin wrapper a python)
├── docs/
│   ├── superpowers/{specs,plans}/           # Val's workflow
│   ├── architecture/                        # design docs
│   ├── adapters/                            # cómo escribir cada shape (4 docs)
│   └── primitives/                          # API reference
├── engine/                                  # las 6 primitives (Python)
│   ├── ingest/
│   ├── process/
│   ├── output/
│   ├── query/
│   ├── memory_loop/
│   └── qa_loop/
├── helpers/                                 # rufino_helpers (Python, versionado)
│   ├── v1/
│   └── ...
├── wizard/
│   ├── system_prompt.md                     # el system prompt completo
│   ├── patterns/                            # 6 patterns iniciales (un md cada uno)
│   └── checklist.md                         # checklist invisible
├── runtime/                                 # plumbing
│   ├── scheduler/                           # launchd/cron/systemd abstraction
│   ├── sandbox/                             # transform.py sandbox
│   ├── transaction_log/                     # bootstrap rollback
│   ├── secrets/                             # Keychain abstraction
│   └── prereq_checker/                      # catalog de checks
├── mcp_server/                              # ask-rufino MCP server
├── validators/                              # uno por shape (worker/vertical/template)
└── tests/                                   # pytest, fixtures por primitive
```

**Decisiones de stack del repo:**
- **Python primary** — todas las primitives + helpers + sandbox + MCP + wizard runtime
- **Bash solo** en `install.sh`, `upgrade.sh`, `cli/rufino` (delega a Python)
- **Tests:** pytest, fixtures por primitive, smoke tests por shape de adapter
- **Build/release:** sin build step en v1 (Python interpretado + bash); release = tag de git

---

## 9. Distribución

**Decidido 2026-05-16: repo privado de GitHub, en principio.**

- **Modelo de instalación:** `git clone` del repo privado + `./install.sh` que registra el CLI `rufino` en `$PATH`, copia hooks/skills/reglas a `~/.claude/`, instala el MCP server, prepara el sandbox para hooks (sección 4.4). Modelo equivalente al actual de `rufino-notes-and-memory`.
- **Access:** invite-only via GitHub. Val administra quién tiene acceso al repo.
- **Updates:** `git pull` + `./upgrade.sh` (script idempotente que aplica nuevas primitives sin romper adapters generados).
- **El "en principio"** deja abierto migrar a otros canales (Homebrew formula, repo público, marketplace) cuando el framework esté maduro y validado con varios verticales reales. v1 arranca privado para iterar sin exponer cambios breaking a usuarios externos.

**Implicación para el wizard:** el CLI `rufino bootstrap` asume que el user ya clonó el repo + corrió `install.sh`. El instalador puede imprimir al final: *"Listo. Para empezar, corré: `rufino bootstrap`"*.

### 9.1 Política de updates

`rufino upgrade` (equivalente a `git pull + ./upgrade.sh`):

1. **Detecta versión actual** instalada (vía `~/.rufino/version`)
2. **Compara con versión target** (latest del repo)
3. **Aplica migraciones secuenciales** — si versión actual es `v1.2` y target es `v1.5`, corre `upgrade-v1.3.sh`, `upgrade-v1.4.sh`, `upgrade-v1.5.sh` en orden
4. **Cada upgrade script es idempotente** — se puede re-correr sin efectos secundarios
5. **Adapters:** si nueva versión del framework requiere nueva versión del helper API (sección 8.2):
   - Default: mantener adapters en versión vieja con warning
   - Opción: `rufino upgrade-adapters --to vN` (con prompt al user explicando los cambios)
6. **Backup automático antes de upgrade** — snapshot de `~/.rufino/` + plists relevantes + entries Keychain en `~/.rufino/backups/<timestamp>/`. Permite revertir si el upgrade rompe algo.

**Rollback de upgrade fallido:** `rufino upgrade --revert` restaura el último backup.

---

## 10. Migración del código actual de Rufino

El repo `rufino-framework` arrancó como copia de `rufino-notes-and-memory` con Fases 2-5 ya agregadas (9 ingestors externos, embeddings, MCP, person resolver, digests, bio, year-review). Mucho de ese código se porta a:

| Componente actual | Destino en el framework |
|---|---|
| `rufino-ingest-*.sh` (9 ingestors) | Adapters de Ingest (Worker adapter shape) |
| `rufino-daily.md`, `rufino-light-cron.md` | Adapters de Process (uno por note_type) |
| `rufino-digest-weekly.sh`, `bio`, `year-review` | Adapters de Output |
| `rufino-search-embeddings.{py,sh}` + `_meta/embeddings.sqlite` | Backend de Query layer |
| MCP server `ask-rufino` (6 tools) | Consumer de Query layer |
| Person resolver | Adapter opcional de Process |
| Hooks + skill `/remember` + reglas `obsidian-memory.md`/`rufino.md` | Memory loop (parametrizado por el wizard) |
| Validador de invariantes (`rufino-lint-cron.sh`) | Modo `lint` del Process pipeline + validador del manifest |

Estrategia de migración: incrementar el framework primitive por primitive, portando los componentes existentes a medida que cada primitive cierra contrato. Mantener el código actual operativo en `rufino-notes-and-memory` hasta que el framework tenga paridad funcional + el primer vertical adicional validado.

---

## 11. Estado de implementación

**Diseño cerrado.** Todos los flecos identificados durante el brainstorming están resueltos en las secciones correspondientes:

| Tema | Sección |
|---|---|
| Sandboxing del transform.py | [4.4](#44-hooks-de-código-modelo-b-híbrido) |
| Validador del manifest | [4.5](#45-validador-del-manifest) |
| Rollback transaccional del bootstrap | [4.6](#46-rollback-transaccional-del-bootstrap) |
| Reglas operativas del wizard | [6.9](#69-reglas-operativas-del-wizard-sección-6-del-system-prompt) |
| Prereqs check del sistema | [6.10](#610-prereqs-check-del-sistema) |
| Docs post-bootstrap | [6.11](#611-documentación-generada-post-bootstrap) |
| Versionado del helper API | [8.2](#82-versionado-del-helper-api) |
| Layout del repo | [8.3](#83-layout-del-repo) |
| Distribución (repo privado GitHub) | [9](#9-distribución) |
| Política de updates | [9.1](#91-política-de-updates) |
| Migración del código actual de Rufino | [10](#10-migración-del-código-actual-de-rufino) |

**Pendiente:** implementation plan vía `superpowers:writing-plans` — descomposición en sub-proyectos, orden de implementación, estimación de effort.

---

## 12. Apéndice: ejemplo end-to-end del vertical facultad

Para anclar todo el spec en un caso concreto, este apéndice traza un user (Beto, estudiante) desde la instalación hasta el primer uso real.

### 12.1 Instalación

```bash
git clone https://github.com/valentinoerrandonea/rufino-framework.git ~/rufino-framework
cd ~/rufino-framework
./install.sh
# El instalador registra el CLI `rufino` en PATH, copia hooks/skills a ~/.claude/,
# instala el MCP server, prepara el sandbox.
# Imprime al final:
# "Listo. Para empezar, corré: rufino bootstrap"

rufino bootstrap
# Abre Claude Code con el system prompt del wizard inyectado.
```

### 12.2 Conversación del wizard (resumen)

```
Claude: Hola, vamos a armar tu sistema. Contame qué problema querés resolver
        — ¿qué te gustaría tener centralizado en un solo lugar?

Beto:   Tengo todas mis notas de la facultad dispersas. PDFs en Drive,
        apuntes en cuadernos digitales, papers en Zotero, screenshots de
        whatsapp con compañeros... quiero todo conectado.

Claude: Entiendo. ¿Estás cursando una sola carrera o varias materias paralelas
        de distintos lugares?

Beto:   Una carrera, ML / data science. Ahora estoy en quinto cuatrimestre,
        cinco materias en paralelo.

Claude: Buenísimo. ¿Querés que las cosas se organicen por materia, por tema,
        o por las dos cosas?

Beto:   Por materia primero, dentro de cada materia por tema.

Claude: ¿Tomás notas durante las clases o las repasás después con material
        del profe?

Beto:   Las dos. En vivo en un iPad, después subo PDFs cuando el profe los
        manda.

Claude: ¿Y los papers que te dan para leer — entran como apunte de clase
        o los tenés aparte?

Beto:   Aparte. Son referencia, los uso para escribir TPs.

[continúa la conversación...]

Claude: OK, te resumo lo que vamos a armar:
        [big bang plantilla, sección 6.7]

Beto:   Dale.

[materialización silenciosa, dry-run OK]

Claude: Listo, tu sistema está armado. Tirá un PDF a ~/facultad/inbox/
        para probarlo.
```

### 12.3 Vault resultante

```
~/facultad/
├── perfil.md                           # generado del wizard
├── README.md                            # auto-generado, explica qué hace cada cosa
├── apuntes/                             # vacío, se llena via process-apunte-clase
├── papers/                              # vacío, se llena via process-paper
├── profesores/                          # vacío, se llena via person resolver
├── materias/                            # vacío, se llena cuando user crea materias
├── conceptos/                           # vacío, concept promotion ≥2
├── examenes/                            # vacío
├── tps/                                 # vacío
├── _meta/
│   ├── lint-2026-05-16.json
│   └── embeddings.sqlite                # vacío inicialmente
└── questions/                           # vacío, se llena via Q&A loop

~/.rufino/
├── adapters/
│   ├── ingest/drive-pdfs/
│   │   ├── manifest.yaml
│   │   └── transform.py                  # opcional, generado solo si necesario
│   ├── ingest/calendar/
│   │   └── manifest.yaml
│   ├── process/apunte-clase/
│   │   ├── manifest.yaml
│   │   └── prompt.md
│   ├── process/paper/
│   │   ├── manifest.yaml
│   │   └── prompt.md
│   ├── output/digest-semanal/
│   │   ├── manifest.yaml
│   │   └── templates/digest-semanal.md
│   ├── output/aviso-examen/
│   │   └── manifest.yaml
│   └── memory-loop/facultad/
│       ├── manifest.yaml
│       └── rules/
│           ├── facultad-vocabulary.md
│           └── facultad-conventions.md
└── secrets/                              # OAuth tokens (Drive, Calendar) via Keychain
```

### 12.4 Primer uso

Beto arrastra `clase3-regresion-logistica.pdf` a `~/facultad/inbox/`. Inmediatamente:

1. File watcher detecta nuevo PDF en inbox
2. Ingest adapter `drive-pdfs` lo procesa (extract texto) y declara `process_with: apunte-clase`
3. Process adapter `apunte-clase` dispara con trigger immediate:
   - Carga el adapter
   - Context injectors corren queries al vault (vacío, primera nota)
   - LLM call (Sonnet) → devuelve nota augmentada
   - LLM detecta que la materia es ambigua (no hay materias registradas todavía) → `ask_user(materia_ambigua)`
4. Q&A loop crea `questions/2026-05-16-materia-clase3.md`:

   ```
   # ¿De qué materia es este apunte?

   No tengo materias registradas todavía. El contenido habla de
   regresión logística, gradient descent, cross-entropy loss. Podría
   ser de:
   - Machine Learning I
   - Stats II
   - Optimización numérica

   ## Respondé editando frontmatter
   `answer: nueva` + `nueva_materia: <nombre>`
   ```

5. Beto edita el frontmatter: `answer: nueva`, `nueva_materia: ml-i`
6. Worker detecta answer → resume el processor → completa la nota:
   - Crea `materias/ml-i.md` (sin profesor asignado todavía). Próxima vez que Beto agregue un apunte donde mencione el profe, el Q&A loop preguntará si confirmar para vincular `dicta →`
   - Mueve el apunte a `apuntes/ml-i/2026-05-16-regresion-logistica.md`
   - Indices actualizados (`_index`, `_tags`, etc.)
7. Concept promotion no se dispara todavía (solo 1 mención de `regresion-logistica`)
8. Si esta semana Beto agrega 2 PDFs más mencionando regresión logística → concept promotion crea `conceptos/regresion-logistica.md` automáticamente

### 12.5 Beto usa el MCP server

Tres días después, Beto está laburando en otro proyecto (`~/laburo/proyecto-X/`). Abre Claude Code ahí. Le pregunta:

```
Beto:   Qué me dijo el profe Méndez sobre cross-entropy en mi cursada?
```

Claude (via MCP `ask-rufino`):
```
[invoca search_vault("cross-entropy", mode="hybrid")]
[encuentra 3 apuntes en apuntes/ml-i/]
[invoca get(...) sobre los 3]

Encontré 3 menciones en tus apuntes de ML I:
1. clase3-regresion-logistica.md (2026-05-16): "...usar cross-entropy
   como loss function porque penaliza más fuerte las predicciones..."
2. ...
```

Beto nunca abrió `~/facultad/`. El MCP server hizo el bridge.

---

## 13. Próximos pasos post-spec

Post-aprobación de Val:

1. **Implementation plan** (via `superpowers:writing-plans` skill) — descomponer el framework en sub-proyectos implementables, definir orden, estimar effort
2. Resolver flecos críticos (sección 11) en orden de prioridad
3. Implementar primitives en orden: Memory loop → Process → Ingest → Output → Q&A loop → Query (Query último porque consume las demás)
4. Implementar wizard
5. Validar con primer vertical real (probablemente facultad, por ser distinto del uso actual de Val)
6. Migrar componentes de `rufino-notes-and-memory` (Fases 2-5) a adapters del framework
7. Publicar v1

---

## Referencias

Notas del vault (proyecto `rufino-framework`):
- `proyectos/rufino/rufino-framework/overview.md`
- `proyectos/rufino/rufino-framework/ideaFrameworkEnBlancoWizardConversacional.md`
- `proyectos/rufino/rufino-framework/decisionArquitecturaVariacionEntreVaults.md` (opción C)
- `proyectos/rufino/rufino-framework/decisionPrimitivesCoreV1.md`
- `proyectos/rufino/rufino-framework/draftContratoProcessPrimitive.md`
- `proyectos/rufino/rufino-framework/decisionHooksCodigoAdapters.md` (modelo B)
- `proyectos/rufino/rufino-framework/draftSweepPrimitivesAltoNivel.md`
- `proyectos/rufino/rufino-framework/decisionShapesAdapterHeterogeneos.md` (4 shapes)
- `proyectos/rufino/rufino-framework/decisionWizardModeloDeInteraccion.md`
- `proyectos/rufino/rufino-framework/decisionWizardDiccionarioYCierre.md`

Filosofía y contexto:
- `proyectos/rufino/rufino-core/rufinoOverview.md`
- `proyectos/rufino/rufino-core/rufinoFilosofia.md`
- `proyectos/rufino/rufino-core/rufinoEcosistemaRepos.md`
- `proyectos/rufino/rufino-notes-and-memory/overview.md` (versión portable v1)
