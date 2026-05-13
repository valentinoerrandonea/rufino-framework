---
tags:
  - proyecto/rufino
  - tipo/meta
  - source/spotify
created: 2026-05-13
updated: 2026-05-13
---

# Spotify — Índice de facts

> Este archivo lo mantiene `rufino-ingest-spotify` (cron semanal, domingo 04:30). No editar manualmente.

## Stats

- Total facts: 0
- Semanas procesadas: 0
- Última corrida: —
- Última semana procesada: —
- Cobertura desde: —

## Facts por tipo

| Tipo | Cantidad |
|------|----------|
| summary-week | 0 |
| top-artist-week | 0 |
| track-recurrent-week | 0 |

## Resumen por semana

| Semana | Tracks | Artistas únicos | Top artist | #1 (plays) | Facts |
|--------|--------|-----------------|------------|------------|-------|
| — | — | — | — | — | — |

## Notas

- Fuente: Spotify Web API `/me/player/recently-played` (limit 50, max ~24h hacia atrás desde la corrida).
- OAuth: refresh token en macOS Keychain (`rufino-spotify-refresh-token`). Generado one-time con `claude/scripts/setup-spotify-auth.sh`.
- Granularidad: agregado por semana ISO (lunes–domingo). Cobertura **parcial** — sólo capturamos el snapshot del weekend si el cron sólo corre los domingos.
- Facts emitidos: 1 summary + top-5 artistas + tracks recurrentes (>=5 plays, max 10) por semana.
- Ver `docs/spotify-notes.md` para setup OAuth e instrucciones operativas.
