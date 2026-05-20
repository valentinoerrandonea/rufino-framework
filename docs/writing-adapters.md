# Writing adapters

Guía para autores de adapters — qué son, cómo escribirlos, qué validador corre contra ellos.

> **Nota.** En el flow normal, los adapters los **genera el wizard** durante el bootstrap. Esto es la guía para casos donde necesitás escribir uno a mano: re-bootstrap incremental, vertical no cubierto por patterns, contribución upstream de un adapter genérico, etc.

## Las 4 shapes

Los adapters no tienen todos la misma forma — hay 4 shapes, uno por familia de primitive:

| Shape | Usado por | Estructura |
|---|---|---|
| **Worker adapter** | Ingest, Process, Output | Carpeta con `manifest.yaml` + prompt/template + opcional `transform.py` |
| **Service primitive** | Query | API pura, no tiene adapter |
| **Vertical config** | Memory loop | Carpeta con `manifest.yaml` + `rules/*.md` |
| **Question template** | Q&A loop | Archivo único: markdown + frontmatter |

Detalle individual:
- [adapters/worker-adapter.md](adapters/worker-adapter.md)
- [adapters/vertical-config.md](adapters/vertical-config.md)
- [adapters/question-template.md](adapters/question-template.md)
- [adapters/service-primitive.md](adapters/service-primitive.md)

## El validador

Antes de instalar / activar cualquier adapter, el framework corre un validador (uno por shape). Errores **bloquean** install; warnings loggean.

Reglas comunes que aplican a casi todos los manifests:

- **Schema YAML válido** — sintácticamente bien-formado.
- **Required fields presentes** — varía por shape.
- **Triple vocabulary no usa keywords reservados** — `type`, `id`, `created`, `updated`, `tags`.
- **Tag axes sin overlap** entre sí.
- **Paths absolutos prohibidos** en `destination_path` — siempre relativos al vault. El validador rechaza paths que empiezan con `/` o paths que se escapan vía `..`.
- **Referencias a otros adapters** (ej: `process_with: <name>`) — el target tiene que existir.
- **Si declara `transform_hook`**: archivo existe + path no se escapa de `adapter_dir`. El runner lo invoca entre fetch/write (Ingest) o entre VALIDATE/CONSOLIDATE (Process) con graceful degrade ante errores.
- **Si declara `template`**: archivo existe + placeholders válidos.

El validador vive en `src/rufino/runtime/validator_base.py` (clase base + protocolo) y se especializa por shape en cada engine.

## Ingest adapter

**Shape:** Worker adapter
**Path:** `~/.rufino/adapters/ingest/<adapter_name>/`
**Files:**

```
ingest/<adapter_name>/
├── manifest.yaml         # required
├── fetcher.py            # opcional: si querés lógica de fetch custom
└── transform.py          # opcional — invocado entre fetch y write (v0.2.0+)
```

### Manifest

```yaml
adapter_name: <kebab-case>            # ej: drive-pdfs
source_name: <slug>                   # ej: gdrive
schedule: "<cron-expression>"         # ej: "*/30 * * * *"
auth:
  type: oauth2 | api_key | none
  keychain_service: <slug>            # ej: rufino-gdrive-oauth (si OAuth)
  refresh_endpoint: <url>             # si OAuth

output_mode: emit_fact | import_raw | emit_augmented

# === emit_fact-specific ===
emits: [<entity_type>, ...]           # ej: [transaccion]
fact_schema:
  <field>: <type>                     # ej: id: string, monto: number
destination:
  facts: <path-template>              # ej: belo/facts/<YYYY-MM-DD>-<id>.md
  raw: <path-template>                # ej: belo/raw/<id>.json
dedup_by: <field-name>                # ej: id

# === import_raw-specific ===
target_inbox: <relative-path>         # ej: rufino/inbox/
process_with: <process-adapter-name>  # ej: apunte-clase
trigger: immediate | defer            # default: immediate

# === emit_augmented-specific (DEFERIDO a v1.1) ===
process_inline_with: <process-adapter-name>

# === opcional ===
transform_hook: ./transform.py        # opcional — invocado entre fetch y write (v0.2.0+)
```

### Ejemplo: Belo (transacciones financieras)

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

### fetcher.py (opcional)

Si tu Ingest necesita lógica de fetch custom (típico para casi todos), creá un `fetcher.py` en el mismo dir del manifest:

```python
# ~/.rufino/adapters/ingest/belo/fetcher.py
from typing import Iterator
from rufino.helpers.v1 import keychain_secret, query_vault


def fetch(cursor: str | None) -> Iterator[dict]:
    """
    Yield records from the source starting at `cursor`.
    Each record must match the `fact_schema` declared in manifest.yaml.
    """
    token = keychain_secret("rufino-belo-oauth")
    # ... API calls ...
    for tx in response.json()["transactions"]:
        yield {
            "id": tx["id"],
            "monto": tx["amount"],
            "moneda": tx["currency"],
            "fecha": tx["date"],
            "cuenta": tx["account"],
            "contraparte": tx["counterparty"],
        }


def next_cursor(record: dict) -> str:
    """Return the cursor to persist after processing `record`."""
    return record["id"]
```

El runner se carga vía `importlib`, llama a `fetch(cursor)`, valida cada record contra `fact_schema`, dedupea, escribe al vault, y persiste el cursor (vía `next_cursor`).

Si tu adapter no tiene `fetcher.py`, el runner usa un fetcher genérico — útil para fuentes simples (file watcher, glob).

### Doc completo del primitive

[primitives/ingest.md](primitives/ingest.md)

---

## Process adapter

**Shape:** Worker adapter
**Path:** `~/.rufino/adapters/process/<adapter_name>/`
**Files:**

```
process/<adapter_name>/
├── manifest.yaml         # required
├── prompt.md             # required
└── transform.py          # opcional — invocado entre VALIDATE y CONSOLIDATE (v0.2.0+)
```

### Manifest

```yaml
adapter_name: <kebab-case>            # ej: apunte-clase
note_type: <snake_case>               # ej: apunte_clase

applies_when:
  source_dir: <relative-path>         # ej: rufino/inbox/
  matches_pattern: ["*.pdf", "*.md", "*.txt"]

llm: sonnet | haiku | opus
mode_default: full | light
batch_size: <int>                     # opcional; default 10. Notas por worker en
                                      # `rufino process-batch`. Entero positivo
                                      # (>=1). Lo overridea el flag --batch-size.

output_schema:
  required:
    <field>: <type>                   # ej: materia: { type: enum_dynamic, source: "tags: materia/" }
  optional:
    <field>: <type>

triple_vocabulary:
  - <relation>                        # ej: tema-de, expuesto-por, extiende, referencia

tag_axes:
  - { axis: <name>, format: "<axis>/<slug>", required: true | false, min: <int> }

destination_path: "<template-with-{frontmatter-fields}>"   # SIEMPRE relativo

qa_triggers:
  - { name: <name>, condition: "<expression>" }

context_injectors:
  - { name: <name>, query: "<query-expression>" }

transform_hook: ./transform.py        # opcional — invocado entre VALIDATE y CONSOLIDATE (v0.2.0+)
```

### Ejemplo: apunte-clase (vertical facultad)

```yaml
adapter_name: apunte-clase
note_type: apunte_clase

applies_when:
  source_dir: rufino/inbox/
  matches_pattern: ["*.pdf", "*.md", "*.txt"]

llm: sonnet
mode_default: full
batch_size: 10

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

### prompt.md

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

### Doc completo del primitive

[primitives/process.md](primitives/process.md)

---

## Output adapter

**Shape:** Worker adapter
**Path:** `~/.rufino/adapters/output/<adapter_name>/`
**Files:**

```
output/<adapter_name>/
├── manifest.yaml         # required
├── templates/<name>.md   # required (typical layout)
└── transform.py          # opcional — invocado tras render del output (v0.2.0+)
```

### Manifest

```yaml
adapter_name: <kebab-case>
trigger:
  type: cron | on_event
  expression: "<cron>"                # si type=cron
  event: <event-name>                 # si type=on_event
  filter: "<expression>"              # si type=on_event

query:
  - { name: <name>, expression: "<query>" }

template: ./templates/<name>.md

delivery:
  - { channel: file, path: "<path-template>" }
  - { channel: email, to: "<addr>", subject: "<subject>" }
  - { channel: webhook, url: "<url>" }
  - { channel: push, title: "<title>" }
```

### Channels built-in

| Channel | Schema en `delivery` | Helpers |
|---|---|---|
| `file://` | `{ channel: file, path: "<path>" }` | Path relativo al vault |
| `email://` | `{ channel: email, to: "...", subject: "..." }` | SMTP via Keychain (`smtp-rufino`) |
| `webhook://` | `{ channel: webhook, url: "<https-only>", method: POST }` | Solo `http(s)://` schemes; timeouts a 30s |
| `push://` | `{ channel: push, title: "...", body: "..." }` | macOS via `osascript`, Linux via `notify-send` |

Cada channel valida sus inputs (path traversal en file, scheme en webhook, escape en push). Errores de delivery se colectan en `result.errors` sin tirar el dispatcher entero.

### Ejemplo: digest-semanal

```yaml
adapter_name: digest-semanal
trigger:
  type: cron
  expression: "0 18 * * 5"            # viernes 18:00

query:
  - name: notas_semana
    expression: "created >= last_monday() AND type IN [apunte_clase, paper]"
  - name: topics_nuevos
    expression: "concept_promotions WHERE created >= last_monday()"

template: ./templates/digest-semanal.md

delivery:
  - channel: email
    to: "beto@example.com"
    subject: "Digest semanal: {{ topics_nuevos | length }} topics nuevos"
  - channel: file
    path: "digests/{{ today() }}-semanal.md"
```

### templates/digest-semanal.md

```markdown
# Digest semanal — {{ today() }}

## Esta semana viste

{% for nota in notas_semana %}
- [[{{ nota.slug }}]] ({{ nota.materia }}) — {{ nota.summary }}
{% endfor %}

## Topics nuevos detectados

{% for topic in topics_nuevos %}
- **{{ topic.name }}** ({{ topic.count }} menciones) — promovido a [[conceptos/{{ topic.slug }}]]
{% endfor %}
```

### Ejemplo: meeting-prep (on_event)

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
  - channel: file
    path: "meetings/<event.attendee>/<YYYY-MM-DD>-1on1.md"
  - channel: email
    to: "manager@empresa.com"
    subject: "1:1 prep: <event.attendee>"
```

### Doc completo del primitive

[primitives/output.md](primitives/output.md)

---

## Memory loop adapter

**Shape:** Vertical config
**Path:** `~/.rufino/adapters/memory_loop/<adapter_name>/`
**Files:**

```
memory_loop/<adapter_name>/
├── manifest.yaml
└── rules/
    ├── <vertical>-vocabulary.md
    └── <vertical>-conventions.md
```

### Manifest

```yaml
adapter_name: <kebab-case>
vertical_name: <slug>

entity_types: [<type>, ...]           # ej: [apunte_clase, materia, profesor, paper, tp, examen]

note_destinations:
  <type>: "<path-template>"           # ej: apunte_clase: "apuntes/<materia>/<YYYY-MM-DD>-<slug>.md"

rule_extensions:
  - ./rules/<vertical>-vocabulary.md
  - ./rules/<vertical>-conventions.md
```

### Qué hace el installer

`install-memory-loop` copia las reglas a `~/.claude/rules/common/<vertical>-*.md` y registra el adapter en `~/.claude.json` (para que el hook init lo carge). Todo via `TransactionLog` → falla = rollback completo.

Las reglas son markdown que Claude lee al iniciar cada sesión — definen vocabulary del vertical, cuándo crear qué tipo de nota, etc.

### Ejemplo: rules/facultad-vocabulary.md

```markdown
# Vocabulario del vertical facultad

## Tipos de entidad

- **apunte_clase** — nota de clase. Vive en `apuntes/<materia>/<YYYY-MM-DD>-<slug>.md`.
- **materia** — una materia de la carrera. Vive en `materias/<slug>.md`.
- **profesor** — persona que dicta. Vive en `profesores/<slug>.md`.
- **paper** — paper académico. Vive en `papers/<materia>/<slug>.md`.

## Triples canónicos

- `tema-de` — apunte tema-de materia
- `expuesto-por` — apunte expuesto-por profesor
- `dicta` — profesor dicta materia
- `referencia` — apunte/paper referencia paper

## Convenciones

- Si Val menciona un profesor que no existe, sugerí guardarlo como persona con tag `profesor/`.
- Si Val menciona una materia que no está registrada, preguntale si crearla.
- Notas de clase siempre van por materia, dentro por fecha-slug.
```

### Doc completo del primitive

[primitives/memory-loop.md](primitives/memory-loop.md)

---

## Q&A template

**Shape:** Question template
**Path:** `~/.rufino/qa-templates/<template-name>.md`

Un archivo único, sin carpeta.

### Estructura

```markdown
---
template_name: <snake_case>
required_context: [<field1>, <field2>, ...]
expected_answer: "<descripción del formato>"
---

# <pregunta concreta>

{% for opt in candidate_options %}
- **[[{{ opt.slug }}]]** ({{ opt.confidence }}% — {{ opt.reason }})
{% endfor %}

## Respondé editando frontmatter
`answer: "<slug>"`
```

### Ejemplo: materia_ambigua

```markdown
---
template_name: materia_ambigua
required_context: [apunte_slug, candidate_materias, evidence]
expected_answer: "<slug>" | "nueva" | "ninguna"
---

# ¿De qué materia es este apunte?

Encontré candidatos:
{% for opt in candidate_materias %}
- **[[{{ opt.slug }}]]** ({{ opt.confidence }}% — {{ opt.reason }})
{% endfor %}

## Evidencia
{{ evidence }}

## Respondé editando frontmatter
`answer: "<slug>"` | `answer: "nueva"` + `nueva_materia: "<slug>"` | `answer: "ninguna"`
```

### Cómo se invocan desde código

Desde un Process adapter (o cualquier consumer del Q&A primitive):

```python
from rufino.engine.qa.api import QALoopAPI

api = QALoopAPI(vault_root=..., state_dir=...)
q_id = api.ask_user(
    template_name="materia_ambigua",
    context={
        "apunte_slug": "clase3-regresion-logistica",
        "candidate_materias": [
            {"slug": "ml-i", "confidence": 70, "reason": "Habla de gradient descent"},
            {"slug": "stats-ii", "confidence": 30, "reason": "Menciona cross-entropy"},
        ],
        "evidence": "Tópicos: regresión logística, gradient descent, cross-entropy loss",
    },
    adapter_name="process-apunte-clase",
    adapter_state={...},   # state opaco que se preserva hasta resumption
)
```

El framework crea `<vault>/questions/2026-05-17-materia-clase3.md`, registra el callback, y devuelve el `q_id`. Cuando el usuario edita el `answer:` y se corre `rufino qa-poll`, el callback se invoca con el answer + el state preservado.

### Reglas de slug / template name

- `slug`s y `template_name`s con `/` son rechazados — defensa contra path traversal.
- Answers que sean **YAML barewords** (`yes`, `no`, números sin quotes) son rechazadas: el template tiene que pedirle al usuario que escriba `answer: "yes"` con comillas. El parser falla loud — no se silencia.
- `adapter_state` se freeza recursivamente con `MappingProxyType` antes de persistir → no podés mutarlo después de `ask_user`.

### Doc completo del primitive

[primitives/qa-loop.md](primitives/qa-loop.md)

---

## Patrones que aplican a todos los adapters

### Idempotencia es no-negociable

Si tu adapter se corre dos veces con el mismo input, tiene que producir el mismo output. Concretamente:

- **Ingest:** dedup por `dedup_by` field; cursor no avanza si hubo errores.
- **Process:** una nota ya procesada (con frontmatter `processed_at:` presente) no se re-procesa.
- **Output:** un delivery duplicado (mismo path + mismo render) se detecta y skipea.
- **Memory loop:** el installer chequea si las reglas ya están instaladas antes de copiar.

### Path traversal está bloqueado

Todas las path templates (`destination`, `template`, `path` en delivery) se validan contra path traversal — el resolved path debe estar dentro del vault o del adapter dir. Esto es defensa profunda: ningún adapter (ni siquiera uno generado por el wizard) puede escribir fuera de sus dominios.

### Mutación recursivamente prohibida

Los manifests parseados se freezan con `MappingProxyType` + tuplas recursivas. Si tu código intenta mutar un manifest (`manifest["new_field"] = "x"`), tira `TypeError`. Eso evita bugs donde un dispatcher mute state shared.

### CRLF normalization

Todos los parsers de frontmatter normalizan CRLF → LF para que un archivo escrito en Windows no se rompa. Si escribís frontmatter raw, vos también.

### YAML safe loading

Usá `yaml.safe_load` y `yaml.safe_dump`, **nunca** `yaml.load` con loader default — ese permite ejecutar código arbitrario. El framework respeta esto en todos lados.

---

## Workflow recomendado para escribir un adapter

1. **Identificá el primitive y el shape.** ¿Es Ingest, Process, Output, Memory loop, o Q&A?
2. **Leé el primitive doc** correspondiente en [`primitives/`](primitives/).
3. **Leé el shape doc** correspondiente en [`adapters/`](adapters/).
4. **Mirá un adapter existente** como referencia. Los del wizard arrancan en `~/.rufino/adapters/` después de un bootstrap.
5. **Escribí el manifest** primero. Corré el validador (lo ejecuta el engine cuando intenta cargar el adapter — vas a ver los errores en stderr).
6. **Escribí el prompt/template** segundo.
7. **Corré el adapter una vez** vía la CLI (`rufino ingest`, `rufino process --mode light`, `rufino output`).
8. **Itera** sobre el prompt mirando los outputs en el vault.
9. **Cuando funcione, agregalo al wizard** — si es un pattern genérico que otros usuarios podrían querer, considerá contribuirlo a `src/rufino/wizard/patterns/` para que el wizard sepa generarlo.

## Helpers expuestos por el framework

Disponibles en `rufino.helpers.v1`:

```python
from rufino.helpers.v1 import (
    query_vault,       # search/traverse del vault
    keychain_secret,   # acceso a Keychain por service name
    cursor_persist,    # guardar/leer cursor para Ingest
    dedup_check,       # check dedup set para Ingest
    fact_validate,     # validar un record contra un schema
    ask_user,          # crear una Q&A (helper sobre QALoopAPI)
    deliver,           # delivery channel-agnostic (wrapper sobre channels)
    render_template,   # jinja2 con StrictUndefined
)
```

Versionados con semver. El framework mantiene compatibilidad 2 versiones — un adapter declarando `helper_version: 1` sigue funcionando bajo `v2`, con deprecation warning. Bajo `v3` se rompe.
