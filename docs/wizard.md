# El wizard conversacional

Cómo conduce Claude el bootstrap, qué hace por debajo, y cómo cambiarlo si querés.

## Qué es

Cuando corrés `rufino bootstrap`, el CLI no muestra prompts ni preguntas pre-escritas. Lo que hace es:

1. Buildea un **system prompt rico** con `src/rufino/wizard/system_prompt_assembler.py`
2. Lanza `claude -p <system-prompt>` con un toolset restringido: `Read`, `Write`, `Bash(rufino materialize:*)`, `Bash(rufino query:*)`
3. La conversación entera transcurre dentro de esa instancia de Claude. El framework no tiene state propio mientras la entrevista sucede

El system prompt es lo que **transforma a Claude en el wizard** — le da identidad, lenguaje, objetivos, reglas operativas, catálogo de patterns, y un esquema de output esperado (la `WizardSpec` JSON).

## Anatomía del system prompt

El assembler arma 11 secciones (todas templates jinja2 en `src/rufino/wizard/`):

| # | Sección | Archivo / fuente |
|---|---|---|
| 1 | Identidad y rol del wizard | `system_prompt_assembler.py` (literal) |
| 2 | Lenguaje user-facing (palabras prohibidas + traducciones) | `language_rules.md` |
| 3 | Conocimiento del runtime (primitives, shapes, transformers, channels) | `system_prompt_assembler.py` |
| 4 | Patterns iniciales (6) | `patterns/*.md` |
| 5 | Reglas de traducción lenguaje user → pattern | `language_rules.md` |
| 6 | Reglas operativas de conversación | `operative_rules.md` |
| 7 | Tracking de objetivos (checklist invisible) | `checklist.md` |
| 8 | Output esperado (estructura de adapters a generar) | `spec_schema.py` (canónico) |
| 9 | Features distintivas a comunicar siempre | `system_prompt_assembler.py` |
| 10 | Features opcionales según vertical | `system_prompt_assembler.py` |
| 11 | Reglas de presentación del big bang | `system_prompt_assembler.py` |

Inspeccionalo con:

```bash
rufino bootstrap --dry-run
```

Eso imprime el prompt entero sin lanzar Claude.

## Lenguaje user (sección 2)

**Palabras prohibidas** — Claude no las usa con el usuario, jamás:

```
manifest, adapter, primitive, frontmatter, triple, schema, vocabulary,
ingest, output_mode, transform.py, output dispatcher, query layer,
memory loop, Q&A loop, MCP, RAG, embedding, augmentation, slug
```

**Traducciones mentales** (decir → en vez de):

| Lenguaje user (sí) | Lenguaje técnico (no) |
|---|---|
| "qué querés trackear" | "qué entidades vas a registrar" |
| "de dónde vienen tus datos" | "qué fuentes vas a configurar" |
| "cómo querés que se organicen" | "qué taxonomía / tags" |
| "qué resúmenes te servirían" | "qué outputs vas a generar" |
| "cuando agregás algo, qué pasa" | "qué Process adapter dispatcha" |
| "armemos tu sistema" | "voy a generar los adapters" |

La idea: el usuario debería poder usar el wizard sin saber nada de la arquitectura interna. Si una palabra técnica aparece en su boca, Claude la traduce a algo concreto en vez de adoptarla.

## Patterns (sección 4)

Los patterns son **estructuras abstractas combinables** — un vertical real usa 2-3 mezclados. Catálogo inicial (en `src/rufino/wizard/patterns/`):

| Pattern | Señales en el lenguaje del usuario | Combinación de primitives |
|---|---|---|
| `discrete_events_with_metadata` | "trackear", "registrar cada vez", "saber cuánto", números+fechas | Ingest emit_fact + Process opcional + Output digest |
| `long_documents_extraction` | "mis apuntes/lecturas/papers", PDFs | Ingest import_raw + Process augmentation + embeddings |
| `person_centric_tracking` | "personas/contactos/empleados", "1:1" | Memory loop persona-central + Q&A dedup + Output meeting-prep |
| `decision_log_with_rationale` | "ADRs", "por qué hicimos X" | Process triple `supersedes` + lint orphans + Output search |
| `temporal_self_observation` | "cómo viene mi semana/mes/año" | Múltiples Ingest + Output bio + year-review |
| `knowledge_graph_projects` | "ideas conectadas", "vault tipo Obsidian" | Memory loop proyecto-central + Process triples ricos + Query grafo |

Cuando el usuario describe su problema, Claude detecta qué patterns matchean y combina. Si después de 2-3 preguntas no encaja ninguno claro, **construye desde primitives básicas** — modo fallback declarativo.

## Reglas operativas (sección 6)

7 heurísticas concretas que Claude aplica durante la conversación (en `operative_rules.md`):

1. **Cerrar línea cuando hay suficiente.** Si Claude tiene info para llenar un campo del checklist, para de preguntar sobre ese tema. No over-engineer.
2. **Repreguntar con opciones concretas si la respuesta es ambigua.** No más open questions seguidas. *"¿es más A o más B?"* en vez de *"¿podés ser más específico?"*.
3. **Dar ejemplos cuando el usuario dice "no sé".** Concretos del vertical inferido, no genéricos.
4. **Tono colaborativo.** *"vamos a armarlo juntos"*, *"contame más"*. No inquisitorial.
5. **Invocar Query layer al inicio.** Chequear si el vault ya tiene algo (debería estar vacío en bootstrap; si no, alertar).
6. **Cerrar el wizard solo cuando checklist completo + validador formal pasa.** No antes, aunque el usuario diga *"ya está, dale"*.
7. **Si el usuario dice "para".** Parar limpio sin protestar, sin guardar nada, sin acusar.

## Checklist interna (sección 7)

Claude lleva mentalmente esta checklist mientras conversa:

```
☐ Vertical identificado
☐ Patrón(es) seleccionado(s) del catálogo
☐ Entidades centrales definidas
☐ Fuentes identificadas
☐ Política de processing (qué pasa cuando llega algo nuevo)
☐ Outputs definidos
☐ Vocabulary del vertical
☐ Usuario confirmó el sistema a armar
```

**No se muestra al usuario** — violaría regla de lenguaje no-técnico. Es referencia interna para que Claude sepa cuándo cerrar el wizard.

Al cierre, **antes** de proponer el big bang, Claude corre internamente un check: si falta algo de la checklist, pregunta más en lenguaje natural. Cuando todo está completo, propone el resumen.

## El big bang (sección 11)

Cuando la checklist está cumplida, Claude muestra un resumen estructurado en lenguaje natural — usando emojis y bullets, traduciendo cada feature técnica al lenguaje user. Ver [`getting-started.md` § "El big bang"](getting-started.md#el-big-bang-resumen-final) para el ejemplo concreto.

Si el usuario confirma con "dale" / "sí" / equivalente:

1. Claude genera la `WizardSpec` JSON en un archivo temporal
2. Llama `rufino materialize --spec <tmp> --vault <X> --claude-home ~/.claude --state-dir ~/.rufino/state`
3. `materialize` valida el spec, ejecuta la materialización transaccional, registra el MCP server
4. Si OK → Claude dice *"Listo, tu sistema está armado. Tirá un PDF a `<vault>/inbox/` para probarlo."*
5. Si falla → Claude lee el error de stderr, lo traduce a lenguaje user, te ofrece reintentar o discutirlo

Si el usuario dice "no encaja": Claude pregunta qué cambiar (sin desarmar la conversación entera) y vuelve al loop. La checklist se "desmarca" lo necesario.

## La `WizardSpec`

JSON que Claude genera y le pasa a `materialize`. Schema canónico en `src/rufino/wizard/spec_schema.py`. Forma simplificada:

```json
{
  "vertical_name": "facultad",
  "patterns": ["long_documents_extraction", "person_centric_tracking"],
  "vault_path": "/Users/beto/facultad",
  "perfil": {
    "user_display_name": "Beto",
    "role_description": "Estudiante de ML / data science, quinto cuatrimestre",
    "...": "..."
  },
  "entities": {
    "materia": { "tag_axis": "materia", "vocabulary": [] },
    "profesor": { "tag_axis": "profesor", "vocabulary": [] },
    "...": "..."
  },
  "adapters": {
    "ingest": [
      { "name": "drive-pdfs", "schedule": "*/15 * * * *", "...": "..." }
    ],
    "process": [
      { "name": "apunte-clase", "note_type": "apunte_clase", "...": "..." }
    ],
    "output": [
      { "name": "digest-semanal", "trigger": "cron", "schedule": "0 18 * * 5" }
    ],
    "memory_loop": [
      { "name": "facultad", "entity_types": ["apunte_clase", "materia", "profesor"] }
    ]
  },
  "qa_templates": [
    { "name": "materia_ambigua", "required_context": ["apunte_slug", "candidate_materias", "evidence"] }
  ]
}
```

Validado por `validate_spec()` antes de materializar. Si es inválido (entity sin vocabulary entry, adapter sin nombre, pattern desconocido), materialize aborta con `SpecError`.

## Cómo invocar el wizard

| Trigger | Cuándo aplica |
|---|---|
| `rufino bootstrap` | First-run post-install. Default path. |
| `rufino bootstrap --dry-run` | Sin lanzar Claude, solo imprime el system prompt — para inspección o reuso |
| Auto-detect (`auto_detect.sh`) | El framework instala una regla global que se dispara cuando Claude Code abre sesión en un dir con framework instalado pero vault vacío. Sugiere *"¿arrancamos a armar tu sistema?"* |
| `/init-rufino` (slash command) | Invocable manual para re-bootstrap o para agregar adapters después |

## Política de interrupción

| Escenario | Comportamiento |
|---|---|
| Usuario cierra a mitad | Cero side effects. Vault queda vacío. La conversación no se persiste. |
| Usuario vuelve | El auto-detect ofrece *"tu bootstrap quedó sin terminar. ¿Lo retomamos desde cero o lo dejamos para otro día?"*. No hay resume — es greenfield siempre. |
| Usuario dice *"para, no quiero seguir"* | Claude para limpio. *"OK, cuando quieras retomamos con `rufino bootstrap`."* |
| Dry-run de adapters falla post-confirmación | Materialización rollback automático (via [transaction log](runtime.md#transaction-log)). Vault vuelve al estado pre-confirmación. |

## Modificar el wizard

Si querés cambiar cómo conduce Claude la entrevista o agregar un pattern nuevo:

### Agregar un pattern

1. Crear `src/rufino/wizard/patterns/<pattern_name>.md` con la estructura:
   ```markdown
   # <pattern_name>
   
   **Trigger language:** <señales en lenguaje user>
   
   **Combinación de primitives:**
   - <primitive a>
   - <primitive b>
   
   **Adapters típicos:**
   - <adapter 1>: <descripción>
   
   **Ejemplos de verticales:**
   - <vertical>: <cómo se usa>
   ```
2. Agregar el nombre a la lista `KNOWN_PATTERNS` en `spec_schema.py`
3. El assembler levanta automáticamente todos los `.md` de `patterns/` en la sección 4

### Modificar las reglas operativas

Editar `src/rufino/wizard/operative_rules.md`. El assembler las inyecta tal cual en la sección 6.

### Modificar el lenguaje user-facing

Editar `src/rufino/wizard/language_rules.md`. Mismo deal.

### Modificar el orden / forma de las 11 secciones

Editar `src/rufino/wizard/system_prompt_assembler.py`. Es jinja2 con StrictUndefined.

### Test del cambio

```bash
rufino bootstrap --dry-run | less
```

O en código:

```python
from rufino.wizard.system_prompt_assembler import build_system_prompt
prompt = build_system_prompt()
print(prompt)
```

## Limitaciones

- **El wizard es markdown-driven.** Toda la calidad de la entrevista depende del system prompt. No hay state machine ni control flow programático — Claude conduce solo.
- **No hay persistencia mid-flow.** Si el usuario cierra Claude a mitad, la entrevista se pierde. Esto es a propósito (alineado con big bang + greenfield) pero significa que sesiones largas son arriesgadas — convidá al usuario a reservarse 10-15 min seguidos.
- **Calidad variable según el modelo.** El wizard fue diseñado y testeado contra Claude Sonnet/Opus. Modelos más chicos pueden saltarse reglas operativas o usar jerga prohibida.
