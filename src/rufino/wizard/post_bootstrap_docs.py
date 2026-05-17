"""Auto-generated user-facing README written into the freshly-materialized vault.

Lenguaje user — NO jerga técnica. Sigue las reglas de language_rules.md
del wizard.
"""
from rufino.wizard.spec_schema import WizardSpec


def render_user_readme(spec: WizardSpec) -> str:
    entities_list = "\n".join(f"- {e.replace('_', ' ')}" for e in spec.entities)
    outputs_section = _render_outputs_section(spec) if spec.outputs else ""

    return f"""# Tu vault Rufino (vertical: {spec.vertical_name})

## Qué tenés acá

Tu vault organiza:

{entities_list}

Cada cosa se guarda automáticamente en la carpeta correcta, sin que tengas
que pensarlo. Las notas relacionadas se conectan entre sí, y los temas que
aparecen seguido se vuelven páginas dedicadas con el tiempo.

## Cómo agregar cosas

Tres caminos:

1. **Tirá archivos al inbox** — cualquier cosa que dejes en `inbox/`
   (PDF, markdown, texto) se organiza automáticamente.
2. **Conversá con Claude Code** — mientras hablás, Claude guarda lo
   valioso al vault sin que te tengas que acordar. Al cerrar la sesión
   te pregunta si hay algo más.
3. **Escribí a mano** — abrí tu editor en el vault y escribí donde quieras.
   Lo organiza después.

## Cómo encontrar cosas

- **Lenguaje natural**: preguntale a Claude algo como
  *"qué tengo sobre X"* y te contesta.
- **Búsqueda directa**: `rufino query "tu pregunta" --vault {spec.vertical_name}`
- **Navegando conexiones**: abrí cualquier nota y seguí los wikilinks.

## Desde otras conversaciones con Claude Code

Incluso fuera del vault, podés preguntarle a Claude sobre tu información.
El servicio queda registrado y disponible en cualquier sesión.
{outputs_section}
## Si algo no funciona

- Logs en `~/.rufino/state/`
- Si el sistema no responde como esperás, revisá `~/.rufino/state/`.
- Para parar todo: detené los crons (los nombres empiezan con `rufino.`).

## Si querés cambiar el sistema

Corré `rufino bootstrap` de nuevo. Te guía para agregar entidades, fuentes
o resúmenes nuevos.
"""


def _render_outputs_section(spec: WizardSpec) -> str:
    items = []
    for out in spec.outputs:
        name = out.get("adapter_name", "output")
        cron = out.get("cron", "")
        suffix = f" ({cron})" if cron else ""
        items.append(f"- **{name.replace('-', ' ')}**{suffix}")
    return "\n\n## Vas a recibir\n\n" + "\n".join(items) + "\n"
