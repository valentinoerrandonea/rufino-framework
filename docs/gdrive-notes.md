# Google Drive ingestor — notas operativas

Ingestor mensual (día 1, 05:00) que escanea Mi unidad de la cuenta personal `valentinoerrandonea2002@gmail.com` via Drive Changes API, descarga archivos nuevos/modificados de tipos relevantes y los mete en `${RUFINO_VAULT_PATH}/rufino/` con `status: queued` para que el cron normal de Rufino los procese.

## Setup OAuth (una sola vez)

Val tiene que crear un OAuth Desktop client en Google Cloud y autorizar el scope readonly de Drive. Después el cron usa el `refresh_token` guardado en Keychain.

### 1. Crear proyecto en Google Cloud Console

1. Andá a https://console.cloud.google.com.
2. Crear un proyecto nuevo (ej "Rufino") o reusar uno existente.

### 2. Habilitar Drive API

1. APIs & Services → Library.
2. Buscar "Google Drive API" → Enable.

### 3. Configurar OAuth consent screen

1. APIs & Services → OAuth consent screen.
2. User Type: **External**.
3. Publishing status: **Testing**.
4. App information: nombre cualquiera (ej "Rufino Drive Ingestor"), email de soporte = tu propio email.
5. Scopes (Add or Remove Scopes):
   - `https://www.googleapis.com/auth/drive.readonly`
   - `https://www.googleapis.com/auth/drive.metadata.readonly`
6. Test users: agregar `valentinoerrandonea2002@gmail.com` como test user. Sin este paso, el OAuth flow va a fallar con "access blocked".

### 4. Crear OAuth client (Desktop app)

1. APIs & Services → Credentials → Create Credentials → OAuth client ID.
2. Application type: **Desktop app**.
3. Name: el que quieras.
4. Click "DOWNLOAD JSON".

### 5. Mover el JSON al path esperado

```bash
mkdir -p ~/.claude/secrets
mv ~/Downloads/client_secret_*.json ~/.claude/secrets/gdrive-credentials.json
chmod 600 ~/.claude/secrets/gdrive-credentials.json
```

### 6. Correr el setup

```bash
~/.claude/scripts/setup-gdrive-auth.sh
```

Esto:
- Levanta un loopback HTTP server en un puerto random.
- Abre el browser (si no se abre, pega la URL que imprime en stderr).
- Esperás que autorices la app con la cuenta `valentinoerrandonea2002@gmail.com`.
- Recibe el `code` por loopback, lo cambia por `refresh_token`.
- Guarda el `refresh_token` en Keychain:
  - Service: `rufino-gdrive-refresh-token`
  - Account: `val`

### 7. Verificar

```bash
security find-generic-password -s rufino-gdrive-refresh-token -a val -w
# Imprime el refresh_token (string largo). Si imprime vacío o error, repetir el setup.
```

## Primer run no importa nada

La Drive Changes API trabaja con `startPageToken`: un cursor que apunta a "estado actual de Drive en este momento". Las llamadas `changes.list` desde ese token solo devuelven cambios **posteriores**.

Eso significa que el primer run del ingestor:
1. Pide `GET /drive/v3/changes/startPageToken`.
2. Guarda el token en `${RUFINO_VAULT_PATH}/gdrive/.state`.
3. Sale sin importar nada.

A partir del **segundo mes**, ya hay un cursor previo y `changes.list` devuelve los archivos modificados entre los dos puntos en el tiempo. Si querés acelerar la cobertura inicial, podés correr el script manualmente apenas terminás el setup OAuth — esa primera corrida registra el cursor, después esperás un par de semanas (o todo un mes) y corrés de nuevo manualmente para ver el delta.

Override manual:
```bash
RUFINO_GDRIVE_FORCE_MONTH=2026-06 ~/.claude/scripts/rufino-ingest-gdrive.sh
```

## Filtros aplicados

El wrapper filtra antes de invocar a Claude:

| Filtro | Razón |
|--------|-------|
| `removed != true` | Skip deletes |
| `file.trashed != true` | Skip trash |
| `file.owners[0].me == true` | Solo Mi unidad, no archivos compartidos por otros |
| `mimeType ∈ {google-doc, pdf, text/plain, text/markdown}` | Out of scope para Rufino: spreadsheets, slides, imágenes, videos |
| `size >= 100 bytes` (excepto Google Docs, no exponen size) | Skip stubs vacíos |

Heurística de **priority** (no filtra, solo etiqueta):
- Si filename o description contiene `meeting`, `transcript`, `minutes`, `notes`, `agenda`, `brief`, `spec`, `summary` → `gdrive_priority: high` en el frontmatter.
- Caso contrario → `gdrive_priority: normal`.

El cron `rufino-cron` puede después usar ese campo para priorizar el orden de procesamiento.

## Conversión a markdown

| Mime | Cómo se baja |
|------|--------------|
| `application/vnd.google-apps.document` | `GET /drive/v3/files/<id>/export?mimeType=text/markdown` (API nativa exporta a markdown). |
| `application/pdf` | `GET /drive/v3/files/<id>?alt=media` → guarda PDF temporal → `pdftotext -layout`. **Requiere `brew install poppler`**. |
| `text/plain`, `text/markdown` | `GET /drive/v3/files/<id>?alt=media` directo. |

Si `pdftotext` no está instalado, el archivo se loguea como error (`status: pdftotext-not-installed`) y no se importa. Instalar con:
```bash
brew install poppler
```

## Output

### Archivos importados

Van a `${RUFINO_VAULT_PATH}/rufino/gdrive-import-<slug>-<YYYY-MM-DD>.md`. Frontmatter:

```yaml
---
tags:
  - source/gdrive
  - tipo/import
gdrive_id: <file-id>
gdrive_owner: valentinoerrandonea2002@gmail.com
gdrive_modified: <ISO>
gdrive_link: <webViewLink>
gdrive_mime: <mime>
gdrive_priority: <high|normal>
created: YYYY-MM-DD
imported: YYYY-MM-DD
status: queued
---

# <Original title>

<markdown content>
```

`status: queued` triggerea que `rufino-cron` lo augmente al día siguiente (tags reales, triples, lo mueve a `rufino/<proyecto>/<tipo>/`).

### Summary fact

1 fact mensual en `${RUFINO_VAULT_PATH}/gdrive/facts/gdrive-import-summary-<YYYY-MM>.md`. Documenta cuántos archivos se vieron, cuántos pasaron filtros, breakdown por tipo.

### Audit trail

Raw JSON de los changes (post-filtro) en `${RUFINO_VAULT_PATH}/gdrive/raw/<YYYY-MM>.json`. Útil para re-procesar si cambia el prompt o debugging.

### State

`${RUFINO_VAULT_PATH}/gdrive/.state`:
```json
{"page_token": "...", "last_run": "ISO", "prev_token": "..."}
```

Si lo borrás, el próximo run se comporta como "primer run" otra vez (registra cursor pero no importa nada). **No tocar a menos que sepas qué hacés.**

## Idempotencia

- Si un archivo con el mismo `gdrive_id` y `gdrive_modified` ya está en `rufino/`, se skipea.
- Si el `gdrive_modified` es más nuevo, se importa con sufijo `-HHMMSS` para no pisar el anterior.
- El summary fact mensual es idempotente por slug (`gdrive-import-summary-<YYYY-MM>`) — re-correr el mismo mes solo actualiza `last_seen`.

## Instalar el cron

Después del setup OAuth:
```bash
# Reemplazar __HOME__ por $HOME en el plist
sed "s|__HOME__|$HOME|g" system/launchd/com.user.rufino-ingest-gdrive.plist \
    > ~/Library/LaunchAgents/com.user.rufino-ingest-gdrive.plist

# Editar el plist: completar RUFINO_VAULT_PATH y RUFINO_DISPLAY_NAME en EnvironmentVariables

# Load
launchctl load ~/Library/LaunchAgents/com.user.rufino-ingest-gdrive.plist

# Trigger manual para test
launchctl start com.user.rufino-ingest-gdrive
tail -f ~/.claude/logs/rufino/rufino-ingest-gdrive.log
```

## Troubleshooting

- **"No existe ~/.claude/secrets/gdrive-credentials.json"**: bajar el JSON desde Cloud Console. Ver setup.
- **"No hay refresh_token en Keychain"**: correr `setup-gdrive-auth.sh`.
- **"access blocked" en el browser**: agregar tu email como test user en OAuth consent screen.
- **"invalid_grant" cuando hace token refresh**: el refresh_token venció o fue revocado. Revocá en https://myaccount.google.com/permissions y re-corré `setup-gdrive-auth.sh`.
- **Primer run después de meses sin correr**: si el `page_token` venció (Google los retiene ~90 días), la API responde con error. Borrá `.state` y arrancá de nuevo (perdés el delta histórico).
- **PDFs no se importan**: `brew install poppler` para tener `pdftotext`.
