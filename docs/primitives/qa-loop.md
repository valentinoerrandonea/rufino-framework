# Q&A loop

Pipeline de preguntas que **solo el usuario puede contestar**. Existe porque a veces el LLM detecta ambigüedad genuina y la opción correcta no es inventar — es preguntar.

## Casos típicos

- **Materia ambigua:** un apunte habla de regresión logística + cross-entropy; podría ser ML I o Stats II. El LLM no debería elegir.
- **Persona nueva:** se menciona "Méndez"; ¿es un profesor, un colega, un coautor de un paper? El LLM no debería asumir.
- **Categorización dudosa:** una transacción podría ser "gasto personal" o "gasto del proyecto X". El LLM no debería decidir.
- **Triple ambiguo:** este paper extiende a este otro o lo contradice? Quizás vos quisiste decir uno y escribiste el otro.

## API

```python
from rufino.engine.qa.api import QALoopAPI

api = QALoopAPI(vault_root=..., state_dir=...)

# Hacer una pregunta
q_id = api.ask_user(
    template_name="materia_ambigua",
    context={
        "apunte_slug": "clase3-regresion-logistica",
        "candidate_materias": [
            {"slug": "ml-i", "confidence": 70, "reason": "..."},
            {"slug": "stats-ii", "confidence": 30, "reason": "..."},
        ],
        "evidence": "Tópicos: regresión logística, gradient descent",
    },
    adapter_name="process-apunte-clase",
    adapter_state={...},                  # state opaco, freezado, devuelto en callback
)

# Más tarde, recuperar la answer
answer = api.get_answer(q_id)         # None si el usuario no contestó todavía
```

## Lifecycle de una pregunta

```
1. Process adapter llama api.ask_user(...)
       ↓
2. Framework:
       ├─→ Crea <vault>/questions/<YYYY-MM-DD>-<slug>.md desde el template
       ├─→ Persiste el callback (con adapter_name + adapter_state) en
       │   <state_dir>/qa/callbacks.json (atomic write, chmod 0600, flock)
       ├─→ Marca la nota source con status: awaiting_user_input
       └─→ Devuelve q_id
       ↓
3. ⏸  Espera. El adapter caller queda blocked.
       ↓
4. Usuario edita el frontmatter de <vault>/questions/<slug>.md:
       answer: "<respuesta>"
       ↓
5. Periódicamente corre: rufino qa-poll --vault X --state-dir Y
       ↓
6. Worker:
       ├─→ Lista questions con answer no vacía
       ├─→ Para cada una:
       │       ├─→ Lookup callback en callbacks.json por q_id
       │       ├─→ Invoke callback(adapter_name, adapter_state, answer)
       │       ├─→ Si OK: mueve question a questions/answered/
       │       │   y borra callback del registry
       │       └─→ Si falla: question + callback quedan intactos (retry-safe)
       ↓
7. Adapter caller resume con el answer + state preservado
```

## Adapter shape: question template

Un archivo único, sin carpeta:

```
~/.rufino/qa-templates/<template-name>.md
```

### Frontmatter

```yaml
---
template_name: <snake_case>
required_context: [<field1>, <field2>, ...]
expected_answer: "<descripción del formato>"
---
```

### Body

Markdown con placeholders jinja2 (`{{ field }}`, `{% for ... %}`). Los placeholders referencian fields del `required_context`.

El framework valida que cada `required_context` esté presente al renderizar — vars faltantes tiran `UndefinedError` loud (no silent default).

### Ejemplo: `materia_ambigua`

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

## CLI

```bash
rufino qa-poll --vault <X> --state-dir <Y>
```

Output:

```
dispatched=<N>
```

Si hubo errores: salen a stderr.

### Estado v0.2.0

`qa-poll` invoca `resume_pending_qa` para cada question con `answer:` no vacío:

- `dispatched` cuenta cuántos workers se relanzaron exitosamente
- Sesión expirada del worker → exit 1 con mensaje claro (la question queda intacta para reintento manual)
- Sin pendings answered → `dispatched=0`, exit 0

## Worker handler-crash-safe

El worker tiene varios safeguards (capturados de code review):

- **El callback se borra del registry _solo_ después** de que el handler completó con éxito. Si el handler crashea, la question + el callback quedan intactos para retry.
- **Errores de file individuales no abortan el poll.** Si una question tiene YAML inválido en su frontmatter, el worker la skipea (con log) y procesa las demás.
- **Slugs / template names con `/` son rechazados.** Defensa contra path traversal.
- **YAML barewords rechazados.** Si el answer es `yes` / `no` / un número sin quotes, el parser falla loud. El template tiene que pedir al usuario que escriba `answer: "yes"` con comillas.

## Callback registry

`<state_dir>/qa/callbacks.json` mantiene el mapeo `q_id → {adapter_name, adapter_state}`. Garantías:

- **Atomic write** (`tmp + rename`).
- **POSIX flock + reload-under-lock** — cross-process safe (dos `qa-poll` simultáneos no corrupten el state).
- **`chmod 0600`** — solo el dueño puede leer (los adapter_states pueden contener info sensible).
- **Raise on corrupt JSON** — no se "recupera silenciosamente" perdiendo state; si la DB se corrompió, el operador tiene que intervenir.

## Inmutabilidad

`adapter_state` se freeza recursivamente con `MappingProxyType` antes de persistir → no podés mutarlo después de `ask_user`. El callback recibe una **deep-copy** del state al ejecutarse (preserva semántica de "snapshot del momento de ask").

## Validador del template

- **Errors:**
  - Frontmatter inválido (YAML mal formado)
  - `template_name` faltante o con `/`
  - `required_context` faltante o no lista
  - Body contiene `{{ var }}` con `var` no declarada en `required_context`
- **Warnings:**
  - `expected_answer` describe formato libremente — sin estructura validable estrictamente. La doc lo indica al usuario; el framework no enforce.

## Ejemplo de uso desde un Process adapter

```python
# Dentro de un Process adapter, post-LLM call:
from rufino.engine.qa.api import QALoopAPI

if llm_result.materia_confidence < 0.7 and len(candidate_materias) >= 2:
    q_id = api.ask_user(
        template_name="materia_ambigua",
        context={
            "apunte_slug": note.slug,
            "candidate_materias": candidate_materias,
            "evidence": llm_result.materia_evidence,
        },
        adapter_name="process-apunte-clase",
        adapter_state={
            "note_path": str(note.path),
            "llm_output": llm_result.as_dict(),
            "indices_to_update_post_resume": [...],
        },
    )
    # El adapter retorna ProcessResult(status="awaiting_user_input", q_id=q_id)
    return ProcessResult(status="awaiting_user_input", q_id=q_id)
```

Cuando el usuario responda y se corra `qa-poll`, el callback registrado:

```python
def callback(adapter_name: str, adapter_state: dict, answer: str) -> None:
    note_path = Path(adapter_state["note_path"])
    llm_output = adapter_state["llm_output"]
    # Resumir el processing con la materia confirmada:
    llm_output["materia"] = answer
    # ... actualizar indices, mover nota, etc ...
```

## Estado v0.2.0

- ✅ Template parser (markdown + jinja2 StrictUndefined + frontmatter)
- ✅ QuestionStore (write/list/mark-answered, archivo movido a `questions/answered/`)
- ✅ CallbackRegistry (atomic write, flock, chmod 0600, raise-on-corrupt)
- ✅ Worker `poll_and_dispatch` (handler-crash-safe, list_pending skip+log)
- ✅ CLI `rufino qa-poll` — resume real vía `resume_pending_qa`; reporta `dispatched=N`

## Referencia

- Shape "question template": [`../adapters/question-template.md`](../adapters/question-template.md)
- Cómo escribir uno: [`../writing-adapters.md#qa-template`](../writing-adapters.md#qa-template)
