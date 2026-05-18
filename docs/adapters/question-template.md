# Question template

Shape de adapter usado por: **Q&A loop**.

Una pregunta no necesita una carpeta con manifest + body + transform — es solo un template markdown. Por eso este shape es **un solo archivo** (sin carpeta).

## Estructura

```
~/.rufino/qa-templates/<template-name>.md
```

`<template-name>` es snake_case. El framework rechaza nombres con `/` (defensa contra path traversal).

## Frontmatter requerido

```yaml
---
template_name: <snake_case>
required_context: [<field1>, <field2>, ...]
expected_answer: "<descripción del formato de respuesta>"
---
```

### Campos

| Campo | Required | Notas |
|---|---|---|
| `template_name` | sí | snake_case, único. Debe matchear el filename (sin `.md`). |
| `required_context` | sí | Lista de fields que el caller debe pasar en `ask_user(context={...})`. El framework valida que cada uno esté presente al renderizar; vars faltantes tiran `UndefinedError` loud. |
| `expected_answer` | sí | Descripción del formato esperado de la respuesta. **Free-form** — no se valida estrictamente. Sirve para que el caller documente al usuario qué tiene que escribir. |

## Body

Markdown con jinja2 (`{{ field }}`, `{% for ... %}`, `{% if ... %}`). Los placeholders referencian fields del `required_context`.

Renderer: jinja2 con `StrictUndefined`. Vars no declaradas tiran `UndefinedError` — el caller se entera al toque, no en silencio.

## Ejemplo: `materia_ambigua`

`~/.rufino/qa-templates/materia_ambigua.md`:

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

## Cómo se invocan

Desde cualquier adapter (típicamente Process) que importe el QA helper:

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
    adapter_state={...},                  # state opaco, freezado, devuelto en callback
)
```

El framework:

1. Carga el template por nombre desde `~/.rufino/qa-templates/<template_name>.md`
2. Valida que cada `required_context[i]` esté en `context`
3. Renderiza con jinja2 + frontmatter (template_name, expected_answer)
4. Escribe `<vault>/questions/<YYYY-MM-DD>-<slug>.md` con un campo `answer:` vacío
5. Persiste el callback (`adapter_name + adapter_state`) en el registry
6. Devuelve `q_id`

## Cómo se contestan

El usuario edita el frontmatter de la pregunta:

```markdown
---
template_name: materia_ambigua
created: 2026-05-17
adapter_name: process-apunte-clase
q_id: 9f2a1c
answer: "ml-i"
---

# ¿De qué materia es este apunte?
...
```

Luego corre:

```bash
rufino qa-poll --vault X --state-dir Y
```

El worker detecta el `answer:` lleno, invoca el callback registrado, y mueve la pregunta a `<vault>/questions/answered/`.

## Reglas de las answers

- **Quoted strings.** El usuario tiene que escribir `answer: "yes"` con comillas. **YAML barewords** (`yes`, `no`, números sin quotes) son rechazadas — el worker tira loud, no silent. El template debe instruir esto.
- **Strings vacías** (`answer:` o `answer: ""`) se consideran "no contestado todavía" — el worker skipea.
- **Whitespace** se preserva — `answer: "  ml-i  "` no se trimea (por si vos lo querés intencional).

## Validador del template

- **Errors:**
  - Frontmatter inválido (YAML mal formado)
  - `template_name` faltante o no string
  - `template_name` con `/` (path traversal protection)
  - `template_name` no matchea el filename
  - `required_context` faltante o no lista
  - `expected_answer` faltante
  - Body contiene `{{ var }}` con `var` no declarada en `required_context`
- **Warnings:**
  - `expected_answer` describe un formato muy abierto (recordatorio: no se valida estrictamente)

## Defensa profunda

- **Path traversal en template_name** — rechazado (debe estar dentro de `~/.rufino/qa-templates/`, sin barras).
- **Path traversal en slug del question file** — rechazado en `QuestionStore`.
- **YAML barewords** rechazadas en answers.
- **Atomic write** del callback registry (`tmp + rename`).
- **POSIX flock** para cross-process safety en `qa-poll`.
- **`chmod 0600`** sobre `callbacks.json` (adapter_states pueden contener info sensible).

## Por qué es shape distinto

Forzar a las Q&A templates a ser carpetas con manifest separado sería ceremonia. El "manifest" de una pregunta es su frontmatter; el "body" es markdown jinja2; no hay código adicional, no hay transform, no hay validation custom más allá del schema.

Un archivo único + frontmatter = el shape mínimo que cumple el contrato.

## Referencia

- Primitive: [`../primitives/qa-loop.md`](../primitives/qa-loop.md)
- Cómo escribir uno: [`../writing-adapters.md#qa-template`](../writing-adapters.md#qa-template)
