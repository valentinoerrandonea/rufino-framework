---
tags:
  - proyecto/rufino
  - tipo/meta
  - source/screentime
created: 2026-05-13
updated: 2026-05-13
---

# Screen Time — Índice de facts

> Este archivo lo mantiene `rufino-ingest-screentime` (cron semanal, domingo 04:00). No editar manualmente.

## Stats

- Total facts: 0
- Semanas procesadas: 0
- Última corrida: —
- Última semana procesada: —
- Cobertura desde: —

## Resumen por semana

| Semana | Total | Top app | #1 (tiempo) | #2 (tiempo) | #3 (tiempo) | Facts |
|--------|-------|---------|-------------|-------------|-------------|-------|
| — | — | — | — | — | — | — |

## Notas

- Fuente: `~/Library/Application Support/Knowledge/knowledgeC.db` (stream `/app/usage`).
- Granularidad: agregado por bundle_id, semana ISO completa (lunes–domingo).
- Facts emitidos: 1 summary + top-5 apps individuales por semana.
- Requiere Full Disk Access para `/bin/bash` (TCC). Ver `docs/screentime-notes.md`.
