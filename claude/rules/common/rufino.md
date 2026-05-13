> **NOTE (rufino-notes-and-memory install):** Antes de copiar esta regla a `~/.claude/rules/common/`, reemplazá manualmente los tokens `$VAULT_PATH` con tu path absoluto al vault y `$DISPLAY_NAME` con tu nombre. Las reglas se cargan como contexto plano por Claude — no hay shell expansion.

# Rufino — Note Vault

$DISPLAY_NAME tiene una carpeta `rufino/` en su vault de Obsidian donde escribe notas crudas que se procesan automáticamente.

## Cuándo activar

Si $DISPLAY_NAME menciona "rufino", "mis notas", o pregunta sobre algo que no es un proyecto de código, buscá en `rufino/`.

## Cómo buscar

1. Leé primero `$VAULT_PATH/rufino/_index.md` — tiene el mapa completo de notas procesadas con categorías, tags y resúmenes.
2. Si necesitás más detalle, leé las notas específicas dentro de las subcarpetas de `rufino/`.
3. Las notas sin procesar (en la raíz de `rufino/`) son crudas — podés leerlas pero no tienen augmentation todavía.

## Qué podés hacer

- Buscar notas por tema, tag, categoría o contenido
- Resumir notas de un período
- Cruzar conexiones entre notas
- Ejecutar el procesamiento manualmente si $DISPLAY_NAME lo pide (usá el prompt de `~/.claude/prompts/rufino-daily.md`)
- Expandir o actualizar la augmentation de una nota específica
- Ver pendientes: leé `$VAULT_PATH/rufino/_pendientes.md`
- Buscar personas: leé `$VAULT_PATH/rufino/_people.md`

## Personas

Cuando $DISPLAY_NAME mencione a una persona que no aparece en `_people.md`, preguntale quién es: nombre, relación (compañero de trabajo, amigo, cliente, etc.), y en qué proyectos está involucrado. Después actualizá `_people.md` con la info.

No preguntes si la persona ya está registrada en `_people.md`.

## Path

`$VAULT_PATH/rufino/`
