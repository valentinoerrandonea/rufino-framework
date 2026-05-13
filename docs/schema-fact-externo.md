# Schema — fact externo

Un **fact externo** es una nota corta derivada automáticamente de una fuente externa (GitHub, Calendar, Chrome, Spotify, etc.). Extiende el patrón ya establecido en `elberr/facts/`.

Las fuentes externas viven en `${RUFINO_VAULT_PATH}/<source>/`. Cada source tiene su propia subcarpeta con `facts/` (output) y opcionalmente `raw/` (audit trail de la data original).

## Estructura de archivo

```
<source>/
├── _index.md          # índice de facts de esta fuente (mantenido por el ingestor)
├── facts/
│   └── <slug>.md      # un fact por evento atómico
└── raw/               # opcional, audit trail del data original
    └── YYYY-MM-DD.json
```

## Frontmatter canónico

```yaml
---
id: <slug>
title: <título descriptivo, en español>
tags:
  - proyecto/val
  - source/<github|calendar|chrome|spotify|screentime|youtube|gdrive|whatsapp|applehealth>
  - tipo/fact
  - tema/<broad>           # opcional pero recomendado
  - concepto/<specific>    # opcional, atomic (no genérico)
  - persona/<name>         # opcional, una por persona involucrada
source: <source>           # mismo valor que el tag `source/<x>`
confidence: high|medium|low
first_seen: YYYY-MM-DD
last_seen: YYYY-MM-DD
sources:                   # refs al raw data o ID externo
  - <archivo-raw>
  - <URL-externa>
triples:
  - { r: references, o: <slug-de-target> }
external_ref:
  type: <commit|pr|issue|event|track|history-item|workout|etc>
  id: <ID externo único>
created: YYYY-MM-DD
updated: YYYY-MM-DD
---

# <título>

<1-3 oraciones describiendo el fact, en español. Términos técnicos en inglés sin traducir.>
```

## Reglas

### Idempotencia
El `id` slug se computa **determinísticamente** desde `external_ref.type:external_ref.id`. Si el archivo ya existe al re-procesar:
- Append `sources[]` dedup
- Update `last_seen`
- **NO** rewrite body, tags, ni triples

Cualquier ingestor debe poder correr 2 veces el mismo día sin duplicar facts.

### Slug
`<source>-<type>-<short-id>` ej:
- `github-commit-rufino-a3f2b1c`
- `github-pr-rufino-dashboard-42`
- `calendar-evento-2026-05-13-1400-meli`
- `spotify-track-alice-chains-rooster-2026-05-12`

Lowercase, kebab-case, sin acentos, máximo 80 chars.

### Tags
- **`source/<x>` siempre** — eje nuevo para filtrar por origen.
- Reusar `tema/<x>` existentes — leer `rufino/_tags.md` antes de inventar.
- `concepto/<x>` solo si es atómico (nombre propio, herramienta, técnica). Evitar genéricos tipo `concepto/actividad`, `concepto/gusto`.
- `persona/<x>` por persona involucrada, si aparece.

### Triples
- Default `references` cuando es ambiguo.
- Si el fact contradice una nota previa: `contradicts`.
- Si refina/supersede: `refines` / `replaces`.
- Mínimo 0 triples (no es obligatorio). Si emitís uno, **el objeto debe existir** en el vault (verificar con grep antes de emitir).

### Confidence
- `high`: source autoritativa (API oficial, SQLite local, dato firmado por el sistema).
- `medium`: inferencia razonable (ej. derivar interés desde watch history).
- `low`: heurística frágil (ej. sentiment de un message).

## Cross-source person resolution

Las personas detectadas por cada ingestor caen en `_people/<name>.md` (existente). Si un ingestor encuentra una persona ambigua (mismo nombre, distintos canales — "Diego" en Slack TELUS vs "Diego diseñador Umbru"), genera una nota en `vault/questions/` para que Val la resuelva (ver `docs/schema-question.md`).

## Audit trail (raw/)

Opcional pero recomendado. Cada ingestor puede dumpear su input crudo a `<source>/raw/YYYY-MM-DD.<ext>` antes de procesar. Sirve para:
- Re-procesar si cambia el prompt
- Debugging de drift entre la fuente y los facts derivados
- Auditoría

No commitear al vault git si los datos son sensibles (configurar `.gitignore`).

## Estado por ingestor

| Source | Schema impl | Cron | Última corrida |
|--------|-------------|------|----------------|
| elberr | sí (precede a este schema) | manual via dashboard | — |
| github | sí | daily 06:30 | — |
| calendar | pendiente Fase 1.2 | — | — |
| screentime | pendiente Fase 1.2 | — | — |
| chrome | pendiente Fase 1.2 | — | — |
| spotify | pendiente Fase 2 | — | — |
| gdrive | pendiente Fase 2 | — | — |
| youtube | pendiente Fase 2 | — | — |
| applehealth | pendiente Fase 3 | — | — |
| whatsapp | pendiente Fase 3 | — | — |

Actualizar esta tabla al cerrar cada fase.
