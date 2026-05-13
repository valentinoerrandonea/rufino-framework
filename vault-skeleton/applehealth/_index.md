---
tags:
  - proyecto/rufino
  - tipo/meta
  - source/applehealth
created: 2026-05-13
updated: 2026-05-13
---

# Apple Health — Índice de facts

> Este archivo lo mantiene `rufino-ingest-applehealth` (cron mensual, día 2 @ 06:00; consume JSONs que un Apple Shortcut iOS deja en `~/Library/Mobile Documents/com~apple~CloudDocs/RufinoHealth/`). No editar manualmente.

## Stats

- Total facts: 0
- Meses procesados: 0
- Última corrida: —
- Último mes procesado: —
- Cobertura desde: —

## Facts por tipo

| Tipo | Cantidad |
|------|----------|
| monthly-summary | 0 |
| workout | 0 |
| sleep-trend | 0 |
| hr-trend | 0 |
| steps-trend | 0 |

## Resumen por mes

| Mes | Workouts | Sleep días | HR días | Steps días | Facts |
|-----|----------|------------|---------|------------|-------|
| — | — | — | — | — | — |

## Notas

- Fuente: Apple HealthKit (workouts, sleep, HR, steps, HRV, flights climbed) via Apple Shortcut iOS programado.
- El Shortcut corre 1 vez por día (recomendado 23:55) en el iPhone, y escribe 4 archivos por jornada (`workouts-YYYY-MM-DD.json`, `sleep-YYYY-MM-DD.json`, `heart-rate-YYYY-MM-DD.json`, `steps-YYYY-MM-DD.json`) en iCloud Drive → `RufinoHealth/`.
- iCloud Drive sincroniza la carpeta al Mac. El cron mensual del Mac la consume.
- Granularidad: agregado mensual. Facts emitidos:
  - 1 summary por mes (siempre, si hay data).
  - 1 fact por workout type con ≥3 sesiones del mes.
  - 1 sleep trend si hay ≥15 noches.
  - 1 HR trend si hay ≥15 días.
  - 1 steps trend si hay ≥15 días.
- Ver `docs/applehealth-notes.md` para el blueprint del Shortcut iOS.
