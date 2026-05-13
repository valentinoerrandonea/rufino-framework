#!/bin/bash
# ─────────────────────────────────────────────────────────────
#  Rufino — Google Drive backfill (one-shot)
#
#  Usa Drive `files.list` (no `changes.list`) para hacer un scan
#  completo de "Mi unidad" sobre un rango de fechas y traer
#  archivos a `${RUFINO_VAULT_PATH}/rufino/`. NO afecta el cursor
#  delta del ingestor mensual.
#
#  Uso:
#    RUFINO_VAULT_PATH=/path/to/vault \
#    RUFINO_GDRIVE_BACKFILL_SINCE=2025-05-13 \
#    bash ~/.claude/scripts/rufino-ingest-gdrive-backfill.sh
#
#  Default SINCE = 12 meses atrás de hoy.
#
#  Requires:
#    - python3, jq, curl
#    - pdftotext (brew install poppler) — solo si hay PDFs
#    - OAuth setup hecho via setup-gdrive-auth.sh
# ─────────────────────────────────────────────────────────────
set -euo pipefail

LOGFILE="${RUFINO_LOG_DIR:-$HOME/.claude/logs/rufino}/rufino-ingest-gdrive-backfill.log"
mkdir -p "$(dirname "$LOGFILE")"
VAULT_PATH="${RUFINO_VAULT_PATH:?RUFINO_VAULT_PATH must be set}"

CREDENTIALS_FILE="$HOME/.claude/secrets/gdrive-credentials.json"
KEYCHAIN_SERVICE="rufino-gdrive-refresh-token"
KEYCHAIN_ACCOUNT="val"

mkdir -p "$VAULT_PATH/gdrive/raw" "$VAULT_PATH/rufino"

# Default SINCE: 12 meses atrás. Aceptar override via env.
SINCE="${RUFINO_GDRIVE_BACKFILL_SINCE:-$(date -v-12m +%Y-%m-%d)}"
SINCE_ISO="${SINCE}T00:00:00.000Z"
DATE_STAMP=$(date +%Y-%m-%d)

echo "=== Rufino gdrive-backfill: $(date) ===" >> "$LOGFILE"
echo "  SINCE: $SINCE_ISO" >> "$LOGFILE"

# Sanity
for bin in jq curl python3; do
    command -v "$bin" >/dev/null 2>&1 || { echo "ERROR: $bin not installed" >> "$LOGFILE"; exit 1; }
done
[ -f "$CREDENTIALS_FILE" ] || { echo "ERROR: $CREDENTIALS_FILE missing. Run setup-gdrive-auth.sh." >> "$LOGFILE"; exit 1; }

REFRESH_TOKEN=$(security find-generic-password -s "$KEYCHAIN_SERVICE" -a "$KEYCHAIN_ACCOUNT" -w 2>/dev/null || true)
[ -n "$REFRESH_TOKEN" ] || { echo "ERROR: no refresh_token in Keychain. Run setup-gdrive-auth.sh." >> "$LOGFILE"; exit 1; }

CLIENT_ID=$(python3 -c "import json; d=json.load(open('$CREDENTIALS_FILE')); k=list(d.keys())[0]; print(d[k]['client_id'])")
CLIENT_SECRET=$(python3 -c "import json; d=json.load(open('$CREDENTIALS_FILE')); k=list(d.keys())[0]; print(d[k]['client_secret'])")

ACCESS_TOKEN=$(curl -s -X POST https://oauth2.googleapis.com/token \
    -d client_id="$CLIENT_ID" -d client_secret="$CLIENT_SECRET" \
    -d refresh_token="$REFRESH_TOKEN" -d grant_type=refresh_token \
    | jq -r '.access_token // empty')
[ -n "$ACCESS_TOKEN" ] || { echo "ERROR: no access_token" >> "$LOGFILE"; exit 1; }

# ────────────────────────────────────
# files.list paginado
# ────────────────────────────────────
QUERY="'me' in owners and trashed=false and modifiedTime > '${SINCE_ISO}' and (mimeType='application/vnd.google-apps.document' or mimeType='application/pdf' or mimeType='text/plain' or mimeType='text/markdown')"
FIELDS='nextPageToken,files(id,name,mimeType,modifiedTime,size,owners(emailAddress,me),webViewLink,description)'

ALL_FILES_TMP=$(mktemp -t rufino-backfill-files-XXXXXX).json
echo '[]' > "$ALL_FILES_TMP"

PAGE_TOKEN=""
PAGES=0
while true; do
    PAGES=$((PAGES + 1))
    [ "$PAGES" -gt 50 ] && { echo "WARN: >50 paginas, abortando" >> "$LOGFILE"; break; }

    if [ -z "$PAGE_TOKEN" ]; then
        RESP=$(curl -s -G -H "Authorization: Bearer $ACCESS_TOKEN" \
            --data-urlencode "q=$QUERY" \
            --data-urlencode "pageSize=1000" \
            --data-urlencode "fields=$FIELDS" \
            --data-urlencode "orderBy=modifiedTime desc" \
            "https://www.googleapis.com/drive/v3/files")
    else
        RESP=$(curl -s -G -H "Authorization: Bearer $ACCESS_TOKEN" \
            --data-urlencode "q=$QUERY" \
            --data-urlencode "pageSize=1000" \
            --data-urlencode "fields=$FIELDS" \
            --data-urlencode "orderBy=modifiedTime desc" \
            --data-urlencode "pageToken=$PAGE_TOKEN" \
            "https://www.googleapis.com/drive/v3/files")
    fi

    if echo "$RESP" | jq -e '.error' >/dev/null 2>&1; then
        echo "ERROR Drive API: $(echo "$RESP" | jq -c '.error')" >> "$LOGFILE"
        rm -f "$ALL_FILES_TMP"
        exit 1
    fi

    BATCH=$(echo "$RESP" | jq '.files // []')
    jq -s 'add' "$ALL_FILES_TMP" <(echo "$BATCH") > "${ALL_FILES_TMP}.merge" && mv "${ALL_FILES_TMP}.merge" "$ALL_FILES_TMP"

    PAGE_TOKEN=$(echo "$RESP" | jq -r '.nextPageToken // empty')
    [ -z "$PAGE_TOKEN" ] && break
done

TOTAL=$(jq 'length' "$ALL_FILES_TMP")
echo "  Total archivos listados: $TOTAL" >> "$LOGFILE"

# Filtro por size (excepto Google Docs que no exponen size)
FILTERED=$(jq '[ .[] | select((.size // "0" | tonumber) >= 100 or .mimeType == "application/vnd.google-apps.document") ]' "$ALL_FILES_TMP")
FILTERED_COUNT=$(echo "$FILTERED" | jq 'length')
echo "  Después de filtro size: $FILTERED_COUNT" >> "$LOGFILE"

# Audit dump
RAW_FILE="$VAULT_PATH/gdrive/raw/backfill-${DATE_STAMP}.json"
jq -n --arg since "$SINCE" --arg ts "$(date -Iseconds)" \
    --argjson total "$TOTAL" --argjson filtered_count "$FILTERED_COUNT" \
    --argjson files "$FILTERED" \
    '{mode: "backfill", since: $since, run_at: $ts, total_files: $total, filtered_count: $filtered_count, files: $files}' \
    > "$RAW_FILE"

rm -f "$ALL_FILES_TMP"

# ────────────────────────────────────
# Procesar cada archivo
# ────────────────────────────────────
IMPORTED=0
SKIPPED=0
ERRORS=0

echo "$FILTERED" | jq -c '.[]' | while IFS= read -r f; do
    FILE_ID=$(echo "$f" | jq -r '.id')
    FILE_NAME=$(echo "$f" | jq -r '.name')
    MIME=$(echo "$f" | jq -r '.mimeType')
    MODIFIED=$(echo "$f" | jq -r '.modifiedTime')
    LINK=$(echo "$f" | jq -r '.webViewLink // ""')
    DESC=$(echo "$f" | jq -r '.description // ""')

    LOWER_TEXT=$(echo "${FILE_NAME} ${DESC}" | tr '[:upper:]' '[:lower:]')
    PRIORITY="normal"
    for kw in meeting transcript minutes notes agenda brief spec summary; do
        echo "$LOWER_TEXT" | grep -q "$kw" && { PRIORITY="high"; break; }
    done

    BASENAME=$(echo "$FILE_NAME" | python3 -c "
import sys, re, unicodedata
s = sys.stdin.read().strip()
s = re.sub(r'\.(pdf|md|txt|docx?)$', '', s, flags=re.IGNORECASE)
s = ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')
s = re.sub(r'[^a-zA-Z0-9]+', '-', s).strip('-').lower()
print(s[:60] or 'untitled')
")
    OUT_NAME="gdrive-import-${BASENAME}-${DATE_STAMP}.md"
    OUT_PATH="$VAULT_PATH/rufino/$OUT_NAME"

    # Idempotencia: si ya existe con mismo file_id y modifiedTime, skip
    EXISTING=$(grep -rlF "gdrive_id: $FILE_ID" "$VAULT_PATH/rufino/" 2>/dev/null | head -1 || true)
    if [ -n "$EXISTING" ]; then
        EXIST_MOD=$(grep -E '^gdrive_modified:' "$EXISTING" | head -1 | sed 's/^gdrive_modified: *//')
        if [ "$EXIST_MOD" = "$MODIFIED" ]; then
            echo "  SKIP: $FILE_NAME (ya importado)" >> "$LOGFILE"
            continue
        fi
        OUT_NAME="gdrive-import-${BASENAME}-${DATE_STAMP}-$(date +%H%M%S).md"
        OUT_PATH="$VAULT_PATH/rufino/$OUT_NAME"
    fi

    CONTENT_TMP=$(mktemp -t rufino-backfill-content-XXXXXX)
    STATUS="ok"
    case "$MIME" in
        "application/vnd.google-apps.document")
            HTTP=$(curl -s -o "$CONTENT_TMP" -w "%{http_code}" \
                -H "Authorization: Bearer $ACCESS_TOKEN" \
                "https://www.googleapis.com/drive/v3/files/${FILE_ID}/export?mimeType=text/markdown")
            [ "$HTTP" = "200" ] || STATUS="export-failed-$HTTP"
            ;;
        "application/pdf")
            PDF_TMP=$(mktemp -t rufino-backfill-pdf-XXXXXX).pdf
            HTTP=$(curl -s -o "$PDF_TMP" -w "%{http_code}" \
                -H "Authorization: Bearer $ACCESS_TOKEN" \
                "https://www.googleapis.com/drive/v3/files/${FILE_ID}?alt=media")
            if [ "$HTTP" != "200" ]; then
                STATUS="download-failed-$HTTP"
            elif ! command -v pdftotext >/dev/null 2>&1; then
                STATUS="pdftotext-not-installed"
            else
                pdftotext -layout "$PDF_TMP" "$CONTENT_TMP" 2>>"$LOGFILE" || STATUS="pdftotext-failed"
            fi
            rm -f "$PDF_TMP"
            ;;
        "text/plain"|"text/markdown")
            HTTP=$(curl -s -o "$CONTENT_TMP" -w "%{http_code}" \
                -H "Authorization: Bearer $ACCESS_TOKEN" \
                "https://www.googleapis.com/drive/v3/files/${FILE_ID}?alt=media")
            [ "$HTTP" = "200" ] || STATUS="download-failed-$HTTP"
            ;;
    esac

    if [ "$STATUS" != "ok" ]; then
        echo "  ERROR: $FILE_NAME: $STATUS" >> "$LOGFILE"
        rm -f "$CONTENT_TMP"
        continue
    fi
    [ -s "$CONTENT_TMP" ] || { echo "  SKIP empty: $FILE_NAME" >> "$LOGFILE"; rm -f "$CONTENT_TMP"; continue; }

    {
        echo "---"
        echo "tags:"
        echo "  - source/gdrive"
        echo "  - tipo/import"
        echo "gdrive_id: $FILE_ID"
        echo "gdrive_owner: valentinoerrandonea2002@gmail.com"
        echo "gdrive_modified: $MODIFIED"
        echo "gdrive_link: $LINK"
        echo "gdrive_mime: $MIME"
        echo "gdrive_priority: $PRIORITY"
        echo "gdrive_backfill: true"
        echo "created: $DATE_STAMP"
        echo "imported: $DATE_STAMP"
        echo "status: queued"
        echo "---"
        echo
        echo "# $FILE_NAME"
        echo
        cat "$CONTENT_TMP"
    } > "$OUT_PATH"
    rm -f "$CONTENT_TMP"

    echo "  IMPORT: $FILE_NAME → $OUT_NAME ($PRIORITY)" >> "$LOGFILE"
done

# Summary log
IMPORTED=$(ls "$VAULT_PATH/rufino/" 2>/dev/null | grep -c "gdrive-import-.*-${DATE_STAMP}" || echo 0)
echo "=== gdrive-backfill done: $(date) ===" >> "$LOGFILE"
echo "  Imported (este run): $IMPORTED" >> "$LOGFILE"
echo "Backfill listo. $IMPORTED archivos en \$RUFINO_VAULT_PATH/rufino/ con status: queued."
echo "El próximo run de rufino-cron (22:00) los va a procesar uno por uno."
