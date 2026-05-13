# Schema — pregunta para Val

El pipeline `questions/` es un canal asíncrono donde Rufino le pregunta a Val cosas que solo él puede contestar: ambigüedades cross-source, decisiones de routing, validaciones.

Vive en `${RUFINO_VAULT_PATH}/questions/`. Cada pregunta es una nota markdown. Val la contesta, le avisa a Claude, y el siguiente cron procesa los cambios y la archiva.

## Estructura

```
questions/
├── README.md           # explicación para Val (cómo contestar)
├── _archive/           # preguntas ya procesadas
│   └── <slug>.md
└── <slug>.md           # preguntas pendientes en raíz
```

## Frontmatter

```yaml
---
id: <slug>
title: <pregunta corta>
type: person-resolution | data-clarification | decision-needed | duplicate-detection
status: pending | answered | archived
created: YYYY-MM-DD
created_by: <ingestor que la generó>
context:
  refs:
    - <slug-de-nota-relacionada>
  data:                    # opcional, payload estructurado para el procesador
    <key>: <value>
priority: high | medium | low
---

# <Pregunta>

<contexto en lenguaje natural, 2-5 oraciones — qué se detectó, por qué hay ambigüedad, qué opciones hay>

## Opciones (si aplica)

- [ ] **Opción A** — descripción
- [ ] **Opción B** — descripción
- [ ] **Otra (escribir abajo)**

## Respuesta de Val

<!-- Val escribe acá. Si elegís una opción de arriba, marcala con [x]. -->

_(esperando)_
```

## Flujo

1. **Genera**: un ingestor o procesador detecta una ambigüedad. Crea `questions/<slug>.md` con `status: pending`.
2. **Contesta**: Val edita la sección "Respuesta de Val". Marca opción con `[x]` o escribe libre. Cambia `status: pending` → `status: answered`. **No** mueve el archivo todavía.
3. **Aviso**: Val le dice a Claude "contesté las questions" en una sesión, o el cron-process-answered lo detecta automáticamente.
4. **Procesa**: un cron / prompt lee preguntas con `status: answered`, aplica los cambios necesarios según `type`, mueve la nota a `_archive/<slug>.md` con `status: archived` y un campo `archived_at: YYYY-MM-DD`.

## Tipos canónicos

| Type | Generado por | Qué procesa |
|------|---------------|-------------|
| `person-resolution` | cross-source person resolver | Merge dos archivos `_people/<x>.md` o registrar que son personas distintas |
| `data-clarification` | cualquier ingestor | Setea un metadato faltante en la nota fuente |
| `decision-needed` | cualquier proceso | Aplica una decisión de routing/tagging propuesta |
| `duplicate-detection` | Rufino lint | Confirma si dos notas son duplicadas y mergea |

## Reglas

- Un question es **idempotente**: si ya existe con mismo slug y `status` en {pending, answered}, no crear duplicado.
- Slug determinístico desde el contenido del trigger (ej. `person-resolution-diego-slack-vs-diego-umbru`).
- Nunca borrar una pregunta — siempre archivar a `_archive/`.
- Si una pregunta queda `pending` más de 30 días, el lint cron debería pingearla en el dashboard.
