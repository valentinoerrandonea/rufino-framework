---
tags:
  - proyecto/rufino
  - tipo/meta
  - source/whatsapp
created: 2026-05-13
updated: 2026-05-13
---

# WhatsApp — Índice de facts

> Mantenido por `rufino-ingest-whatsapp` (cron domingos 05:00). Lee chats vía `whatsapp-web.js` (Puppeteer headless con sesión persistida). No editar manualmente.

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
| chat-frequency-week | 0 |
| recurring-topic-week | 0 |

## Resumen por semana

| Semana | Mensajes recibidos | Mensajes enviados | Chats activos | Top contacto | Facts |
|--------|--------------------|-------------------|---------------|--------------|-------|
| — | — | — | — | — | — |

## Notas

- Fuente: WhatsApp Web (multi-device) via `whatsapp-web.js` con Puppeteer headless. Sesión persistida en `~/.claude/whatsapp-session/`.
- Auth: QR scan one-time con `claude/scripts/setup-whatsapp-auth.sh`. Si la sesión expira, re-correr el setup.
- Granularidad: agregado por semana ISO (lunes-domingo). Cron levanta Puppeteer, scrapea, baja Puppeteer.
- Privacy: el JSON raw **no** contiene texto literal de mensajes. Sólo counts, contactos y keywords agregados para topic extraction.
- Facts emitidos: 1 summary + top-10 contactos por frecuencia + hasta 5 recurring-topic por semana.
- Ver `docs/whatsapp-notes.md` para setup y caveats.
