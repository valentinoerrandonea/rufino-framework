---
tags:
  - proyecto/rufino
  - tipo/meta
  - source/gdrive
created: 2026-05-13
updated: 2026-05-13
---

# Google Drive — Índice de facts

> Este archivo lo mantiene `rufino-ingest-gdrive` (cron mensual, día 1 a las 05:00). No editar manualmente.

## Stats

- Total facts: 0
- Meses procesados: 0
- Archivos importados (acumulado): 0
- Última corrida: —
- Último mes procesado: —
- Cobertura desde: —

## Resumen por mes

| Mes | Total changes | Filtrados | Importados | Errores | Fact |
|-----|---------------|-----------|------------|---------|------|
| — | — | — | — | — | — |

## Notas

- Fuente: Google Drive API v3, scope `drive.readonly` + `drive.metadata.readonly`.
- Cuenta: `valentinoerrandonea2002@gmail.com` (personal, Mi unidad).
- Detección de cambios: `changes.list` con `startPageToken` persistido en `gdrive/.state`.
- **Primer run no importa nada**: solo registra el `startPageToken` inicial. Los cambios se acumulan desde ese cursor hacia adelante. El segundo mes ya ve actividad real.
- Mime types whitelist: Google Docs, PDF, text/plain, text/markdown.
- Skip: spreadsheets, presentations, imágenes, videos, archivos compartidos por otros, trash, archivos <100 bytes.
- Los archivos importados van a `${RUFINO_VAULT_PATH}/rufino/gdrive-import-<slug>-<fecha>.md` con `status: queued` — los procesa `rufino-cron` al día siguiente (augmentation, tags, triples, mover a `rufino/<proyecto>/<tipo>/`).
- Setup OAuth: ver `docs/gdrive-notes.md`.
