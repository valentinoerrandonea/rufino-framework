---
tags:
  - proyecto/rufino
  - tipo/meta
created: 2026-05-13
updated: 2026-05-13
---

# Questions — preguntas pendientes de Val

> Canal asíncrono donde Rufino te pregunta cosas que solo vos podés contestar.

## Cómo contestar

1. Abrí la nota de la pregunta (en raíz de esta carpeta).
2. Editá la sección **## Respuesta de Val**.
   - Si hay opciones, marcá la elegida con `[x]`.
   - Si no, escribí libre.
3. En el frontmatter cambiá `status: pending` → `status: answered`.
4. Avisale a Claude en la próxima sesión: _"contesté las questions"_.
5. El cron-process-answered (o Claude en esa sesión) aplica los cambios y mueve la nota a `_archive/`.

## Tipos de pregunta

| Type | Significado |
|------|-------------|
| `person-resolution` | "Diego de Slack TELUS y Diego diseñador Umbru — ¿son la misma persona?" |
| `data-clarification` | "Encontré una nota sin proyecto asignado, ¿a cuál corresponde?" |
| `decision-needed` | "Esta nueva ingesta detectó X, ¿la incorporamos cómo Y o Z?" |
| `duplicate-detection` | "Las notas A y B se parecen mucho, ¿mergeamos?" |

## Reglas

- Las respuestas son irreversibles una vez procesadas (la nota se mueve a `_archive/`). Releé antes de marcar `answered`.
- Si no estás seguro, dejá la pregunta `pending` — no hay penalidad por demora.
- Si una pregunta no aplica más, podés borrarla manualmente moviéndola a `_archive/` con un campo `archived_reason: cancelled`.

## Stats

- Pendientes: 0
- Respondidas sin procesar: 0
- Archivadas: 0
