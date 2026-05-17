# Question template

Shape usado por: **Q&A loop**.

## Estructura

Un archivo único, sin carpeta:

```
~/.rufino/qa-templates/<template-name>.md
```

## Frontmatter requerido

```yaml
---
template_name: <snake_case>
required_context: [<field1>, <field2>, ...]
expected_answer: "<descripción del formato de respuesta>"
---
```

## Body

Markdown con placeholders jinja2 (`{{ field }}`, `{% for ... %}`). Los placeholders referencian fields del `required_context`.

El framework valida que cada `required_context` esté presente al renderizar.

## Cómo se invocan

Desde cualquier adapter que importe el QA helper:

```python
from rufino.engine.qa.api import QALoopAPI
api = QALoopAPI(...)
q_id = api.ask_user(
    template_name="materia_ambigua",
    context={"apunte_slug": "x", "candidate_materias": [...], "evidence": "..."},
    adapter_name="process-apunte-clase",
    adapter_state={...},
)
```
