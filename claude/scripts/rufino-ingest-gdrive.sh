#!/bin/bash
# ─────────────────────────────────────────────────────────────
#  Rufino — Google Drive ingestor (Mi unidad, cuenta personal)
#  Monthly (Day 1, 05:00). Detecta archivos nuevos/modificados desde
#  el último run via Drive Changes API (delta-based con startPageToken).
#
#  Acción:
#    1. Refresh access token desde Keychain.
#    2. Si no hay state previo → GET startPageToken inicial, NO importa
#       nada históricamente (registra el cursor para próximos runs).
#    3. Si hay state → GET changes desde el page_token, filtra por
#       mime type / ownership / heurística, descarga, convierte a md,
#       y mete cada archivo en `${RUFINO_VAULT_PATH}/rufino/<filename>.md`
#       (donde el cron normal de rufino lo va a procesar).
#    4. Emite un summary fact mensual en `${RUFINO_VAULT_PATH}/gdrive/facts/`.
#    5. Audit dump de la lista de changes en `${RUFINO_VAULT_PATH}/gdrive/raw/<YYYY-MM>.json`.
#    6. Actualiza state con el nuevo startPageToken.
#
#  Requires:
#    - python3, jq, curl
#    - pdftotext (brew install poppler) — solo si hay PDFs
#    - OAuth setup hecho via setup-gdrive-auth.sh
#    - $RUFINO_VAULT_PATH set
# ─────────────────────────────────────────────────────────────
set -euo pipefail

LOGFILE="${RUFINO_LOG_DIR:-$HOME/.claude/logs/rufino}/rufino-ingest-gdrive.log"
mkdir -p "$(dirname "$LOGFILE")"
PROMPT_FILE="$HOME/.claude/prompts/rufino-ingest-gdrive.md"
CLAUDE="$(command -v claude || echo "$HOME/.local/bin/claude")"
VAULT_PATH="${RUFINO_VAULT_PATH:?RUFINO_VAULT_PATH must be set}"
LOCKFILE="$VAULT_PATH/_meta/.ingest-gdrive.lock"

CREDENTIALS_FILE="$HOME/.claude/secrets/gdrive-credentials.json"
KEYCHAIN_SERVICE="rufino-gdrive-refresh-token"
KEYCHAIN_ACCOUNT="val"
STATE_FILE="$VAULT_PATH/gdrive/.state"

mkdir -p "$VAULT_PATH/_meta" "$VAULT_PATH/gdrive/facts" "$VAULT_PATH/gdrive/raw"

# Stale-lock-aware locking
if [ -f "$LOCKFILE" ]; then
    LOCK_PID=$(cat "$LOCKFILE" 2>/dev/null || echo "")
    if [ -n "$LOCK_PID" ] && kill -0 "$LOCK_PID" 2>/dev/null; then
        echo "=== Rufino ingest-gdrive skipped: already running (PID $LOCK_PID) at $(date) ===" >> "$LOGFILE"
        exit 0
    fi
    rm -f "$LOCKFILE"
fi
echo "$$" > "$LOCKFILE"
trap 'rm -f "$LOCKFILE"' EXIT

echo "=== Rufino ingest-gdrive run: $(date) ===" >> "$LOGFILE"

# Sanity: deps
for bin in jq curl python3; do
    if ! command -v "$bin" >/dev/null 2>&1; then
        echo "ERROR: $bin no instalado" >> "$LOGFILE"
        exit 1
    fi
done
if [ ! -f "$PROMPT_FILE" ]; then
    echo "ERROR: Prompt file not found at $PROMPT_FILE" >> "$LOGFILE"
    exit 1
fi
if [ ! -f "$CREDENTIALS_FILE" ]; then
    cat >> "$LOGFILE" <<EOF
ERROR: No existe $CREDENTIALS_FILE.
Correr setup-gdrive-auth.sh primero. Ver docs/gdrive-notes.md.
EOF
    exit 1
fi

# ────────────────────────────────────
# Step 1: Obtener access token fresco
# ────────────────────────────────────
REFRESH_TOKEN=$(security find-generic-password -s "$KEYCHAIN_SERVICE" -a "$KEYCHAIN_ACCOUNT" -w 2>/dev/null || true)
if [ -z "$REFRESH_TOKEN" ]; then
    echo "ERROR: No hay refresh_token en Keychain. Correr setup-gdrive-auth.sh." >> "$LOGFILE"
    exit 1
fi

CLIENT_ID=$(python3 -c "import json; d=json.load(open('$CREDENTIALS_FILE')); k=list(d.keys())[0]; print(d[k]['client_id'])")
CLIENT_SECRET=$(python3 -c "import json; d=json.load(open('$CREDENTIALS_FILE')); k=list(d.keys())[0]; print(d[k]['client_secret'])")

TOKEN_RESPONSE=$(curl -s -X POST https://oauth2.googleapis.com/token \
    -d client_id="$CLIENT_ID" \
    -d client_secret="$CLIENT_SECRET" \
    -d refresh_token="$REFRESH_TOKEN" \
    -d grant_type=refresh_token)

ACCESS_TOKEN=$(echo "$TOKEN_RESPONSE" | jq -r '.access_token // empty')
if [ -z "$ACCESS_TOKEN" ]; then
    echo "ERROR: No se obtuvo access_token. Response: $TOKEN_RESPONSE" >> "$LOGFILE"
    exit 1
fi

# ────────────────────────────────────
# Step 2: Resolver page_token (state)
# ────────────────────────────────────
TARGET_MONTH="${RUFINO_GDRIVE_FORCE_MONTH:-$(date +%Y-%m)}"
RAW_FILE="$VAULT_PATH/gdrive/raw/${TARGET_MONTH}.json"

if [ ! -f "$STATE_FILE" ]; then
    # First run: registrar startPageToken, no procesar nada.
    INIT_RESPONSE=$(curl -s -H "Authorization: Bearer $ACCESS_TOKEN" \
        "https://www.googleapis.com/drive/v3/changes/startPageToken")
    INIT_TOKEN=$(echo "$INIT_RESPONSE" | jq -r '.startPageToken // empty')
    if [ -z "$INIT_TOKEN" ]; then
        echo "ERROR: No se pudo obtener startPageToken inicial. Response: $INIT_RESPONSE" >> "$LOGFILE"
        exit 1
    fi
    jq -n --arg t "$INIT_TOKEN" --arg now "$(date -Iseconds)" \
        '{page_token: $t, last_run: $now, first_run: true}' > "$STATE_FILE"
    echo "  Primer run — registrado startPageToken=$INIT_TOKEN. No se importan archivos históricos." >> "$LOGFILE"
    # Dump empty raw for audit
    jq -n --arg month "$TARGET_MONTH" --arg note "first-run, no changes processed" \
        '{month: $month, note: $note, changes: []}' > "$RAW_FILE"
    echo "=== Rufino ingest-gdrive done (first-run): $(date) ===" >> "$LOGFILE"
    exit 0
fi

PAGE_TOKEN=$(jq -r '.page_token' "$STATE_FILE")
if [ -z "$PAGE_TOKEN" ] || [ "$PAGE_TOKEN" = "null" ]; then
    echo "ERROR: state file corrupto ($STATE_FILE). Borralo y re-corré (te va a costar el delta histórico)." >> "$LOGFILE"
    exit 1
fi

echo "  Page token actual: $PAGE_TOKEN" >> "$LOGFILE"

# ────────────────────────────────────
# Step 3: Pedir changes (paginado)
# ────────────────────────────────────
CHANGES_TMP="$(mktemp -t rufino-gdrive-XXXXXX).json"
echo '[]' > "$CHANGES_TMP"

NEXT_TOKEN="$PAGE_TOKEN"
NEW_START_PAGE_TOKEN=""
PAGES=0
FIELDS='nextPageToken,newStartPageToken,changes(fileId,removed,time,file(id,name,mimeType,modifiedTime,size,trashed,owners(emailAddress,me),parents,webViewLink,description))'

while [ -n "$NEXT_TOKEN" ]; do
    PAGES=$((PAGES + 1))
    if [ "$PAGES" -gt 100 ]; then
        echo "WARN: >100 paginas de changes — abortando loop por seguridad" >> "$LOGFILE"
        break
    fi
    RESP=$(curl -s -G -H "Authorization: Bearer $ACCESS_TOKEN" \
        --data-urlencode "pageToken=$NEXT_TOKEN" \
        --data-urlencode "pageSize=1000" \
        --data-urlencode "spaces=drive" \
        --data-urlencode "fields=$FIELDS" \
        "https://www.googleapis.com/drive/v3/changes")

    if echo "$RESP" | jq -e '.error' >/dev/null 2>&1; then
        echo "ERROR Drive API: $(echo "$RESP" | jq -c '.error')" >> "$LOGFILE"
        rm -f "$CHANGES_TMP"
        exit 1
    fi

    # Append changes
    NEW=$(echo "$RESP" | jq '.changes // []')
    jq -s 'add' "$CHANGES_TMP" <(echo "$NEW") > "${CHANGES_TMP}.merge" && mv "${CHANGES_TMP}.merge" "$CHANGES_TMP"

    NEXT_TOKEN=$(echo "$RESP" | jq -r '.nextPageToken // empty')
    NEW_START_PAGE_TOKEN=$(echo "$RESP" | jq -r '.newStartPageToken // empty')
done

TOTAL_CHANGES=$(jq 'length' "$CHANGES_TMP")
echo "  Changes recibidos: $TOTAL_CHANGES" >> "$LOGFILE"

# ────────────────────────────────────
# Step 4: Filtrar a archivos relevantes
# ────────────────────────────────────
# Reglas:
#   - removed == false / no removido
#   - file.trashed == false
#   - file.owners[0].me == true (Mi unidad)
#   - mimeType en whitelist
#   - size >= 100 (skip stubs vacíos)
FILTERED=$(jq '[ .[]
    | select(.removed != true)
    | select(.file != null)
    | select(.file.trashed != true)
    | select(.file.owners != null and (.file.owners | length) > 0 and .file.owners[0].me == true)
    | select(.file.mimeType == "application/vnd.google-apps.document"
          or .file.mimeType == "application/pdf"
          or .file.mimeType == "text/plain"
          or .file.mimeType == "text/markdown")
    | select((.file.size // "0" | tonumber) >= 100 or .file.mimeType == "application/vnd.google-apps.document")
]' "$CHANGES_TMP")

FILTERED_COUNT=$(echo "$FILTERED" | jq 'length')
echo "  Archivos relevantes tras filtros: $FILTERED_COUNT" >> "$LOGFILE"

# Persist raw audit dump (con changes filtrados + count total para auditoría)
jq -n \
    --arg month "$TARGET_MONTH" \
    --arg ts "$(date -Iseconds)" \
    --argjson total "$TOTAL_CHANGES" \
    --argjson filtered_count "$FILTERED_COUNT" \
    --argjson filtered "$FILTERED" \
    '{month: $month, run_at: $ts, total_changes: $total, filtered_count: $filtered_count, filtered: $filtered}' \
    > "$RAW_FILE"

rm -f "$CHANGES_TMP"

# ────────────────────────────────────
# Step 5: Descargar + convertir + meter en rufino/
# ────────────────────────────────────
IMPORT_RESULTS_TMP="$(mktemp -t rufino-gdrive-imports-XXXXXX).json"
echo '[]' > "$IMPORT_RESULTS_TMP"

if [ "$FILTERED_COUNT" -gt 0 ]; then
    # Stream cada archivo filtrado via jq y procesar uno por uno.
    echo "$FILTERED" | jq -c '.[]' | while IFS= read -r change; do
        FILE_ID=$(echo "$change" | jq -r '.file.id')
        FILE_NAME=$(echo "$change" | jq -r '.file.name')
        MIME=$(echo "$change" | jq -r '.file.mimeType')
        MODIFIED=$(echo "$change" | jq -r '.file.modifiedTime')
        LINK=$(echo "$change" | jq -r '.file.webViewLink // ""')
        DESC=$(echo "$change" | jq -r '.file.description // ""')

        # Heurística "importante": filename o description contiene keywords.
        # Si NO matchea, igual lo importamos — la heurística filtra prioridad,
        # no descarta. Si necesitamos endurecer después, basta con `continue`.
        # Por ahora: log si es heurística-priority, importar siempre.
        LOWER_TEXT=$(echo "${FILE_NAME} ${DESC}" | tr '[:upper:]' '[:lower:]')
        PRIORITY="normal"
        for kw in meeting transcript minutes notes agenda brief spec summary; do
            if echo "$LOWER_TEXT" | grep -q "$kw"; then
                PRIORITY="high"
                break
            fi
        done

        # Slug del filename → lowercase, kebab, sin acentos
        BASENAME=$(echo "$FILE_NAME" | python3 -c "
import sys, re, unicodedata
s = sys.stdin.read().strip()
# strip extension
s = re.sub(r'\.(pdf|md|txt|docx?)$', '', s, flags=re.IGNORECASE)
# strip accents
s = ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')
s = re.sub(r'[^a-zA-Z0-9]+', '-', s).strip('-').lower()
print(s[:60] or 'untitled')
")
        DATE_STAMP=$(date +%Y-%m-%d)
        OUT_NAME="gdrive-import-${BASENAME}-${DATE_STAMP}.md"
        OUT_PATH="$VAULT_PATH/rufino/$OUT_NAME"

        # Si ya existe (mismo file_id ya importado este run o anterior), skip.
        # Match por header gdrive_id en cualquier rufino/<*>.md
        EXISTING=$(grep -rlF "gdrive_id: $FILE_ID" "$VAULT_PATH/rufino/" 2>/dev/null | head -1 || true)
        if [ -n "$EXISTING" ]; then
            # Si el modifiedTime es más nuevo que `gdrive_modified` del archivo
            # existente, re-importar con sufijo. Si es el mismo, skip.
            EXIST_MOD=$(grep -E '^gdrive_modified:' "$EXISTING" | head -1 | sed 's/^gdrive_modified: *//')
            if [ "$EXIST_MOD" = "$MODIFIED" ]; then
                echo "  SKIP (ya importado, sin cambio): $FILE_NAME ($FILE_ID)" >> "$LOGFILE"
                continue
            fi
            # else: re-import bajo nuevo nombre con timestamp único
            OUT_NAME="gdrive-import-${BASENAME}-${DATE_STAMP}-$(date +%H%M%S).md"
            OUT_PATH="$VAULT_PATH/rufino/$OUT_NAME"
        fi

        # Descargar / exportar contenido
        CONTENT_TMP="$(mktemp -t rufino-gdrive-content-XXXXXX)"
        STATUS="ok"
        case "$MIME" in
            "application/vnd.google-apps.document")
                # Export como markdown
                HTTP=$(curl -s -o "$CONTENT_TMP" -w "%{http_code}" \
                    -H "Authorization: Bearer $ACCESS_TOKEN" \
                    "https://www.googleapis.com/drive/v3/files/${FILE_ID}/export?mimeType=text/markdown")
                if [ "$HTTP" != "200" ]; then STATUS="export-failed-$HTTP"; fi
                ;;
            "application/pdf")
                # Bajar PDF, después pdftotext
                PDF_TMP="$(mktemp -t rufino-gdrive-pdf-XXXXXX).pdf"
                HTTP=$(curl -s -o "$PDF_TMP" -w "%{http_code}" \
                    -H "Authorization: Bearer $ACCESS_TOKEN" \
                    "https://www.googleapis.com/drive/v3/files/${FILE_ID}?alt=media")
                if [ "$HTTP" != "200" ]; then
                    STATUS="download-failed-$HTTP"
                    rm -f "$PDF_TMP"
                elif ! command -v pdftotext >/dev/null 2>&1; then
                    STATUS="pdftotext-not-installed"
                    rm -f "$PDF_TMP"
                else
                    pdftotext -layout "$PDF_TMP" "$CONTENT_TMP" 2>>"$LOGFILE" || STATUS="pdftotext-failed"
                    rm -f "$PDF_TMP"
                fi
                ;;
            "text/plain"|"text/markdown")
                HTTP=$(curl -s -o "$CONTENT_TMP" -w "%{http_code}" \
                    -H "Authorization: Bearer $ACCESS_TOKEN" \
                    "https://www.googleapis.com/drive/v3/files/${FILE_ID}?alt=media")
                if [ "$HTTP" != "200" ]; then STATUS="download-failed-$HTTP"; fi
                ;;
        esac

        if [ "$STATUS" != "ok" ]; then
            echo "  ERROR importando $FILE_NAME: $STATUS" >> "$LOGFILE"
            jq --arg id "$FILE_ID" --arg name "$FILE_NAME" --arg mime "$MIME" --arg status "$STATUS" \
                '. + [{file_id: $id, name: $name, mime: $mime, status: $status}]' \
                "$IMPORT_RESULTS_TMP" > "${IMPORT_RESULTS_TMP}.new" && mv "${IMPORT_RESULTS_TMP}.new" "$IMPORT_RESULTS_TMP"
            rm -f "$CONTENT_TMP"
            continue
        fi

        # Sanity check de contenido vacío
        if [ ! -s "$CONTENT_TMP" ]; then
            echo "  SKIP (contenido vacío): $FILE_NAME" >> "$LOGFILE"
            rm -f "$CONTENT_TMP"
            continue
        fi

        # Escribir archivo en rufino/ con frontmatter
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

        jq --arg id "$FILE_ID" --arg name "$FILE_NAME" --arg mime "$MIME" \
           --arg out "$OUT_NAME" --arg priority "$PRIORITY" \
           '. + [{file_id: $id, name: $name, mime: $mime, status: "imported", out: $out, priority: $priority}]' \
            "$IMPORT_RESULTS_TMP" > "${IMPORT_RESULTS_TMP}.new" && mv "${IMPORT_RESULTS_TMP}.new" "$IMPORT_RESULTS_TMP"

        echo "  IMPORT: $FILE_NAME → $OUT_NAME ($PRIORITY)" >> "$LOGFILE"
    done
fi

# ────────────────────────────────────
# Step 6: Actualizar state con nuevo startPageToken
# ────────────────────────────────────
# La Drive API devuelve newStartPageToken solo en la última página.
if [ -n "$NEW_START_PAGE_TOKEN" ]; then
    jq -n \
        --arg t "$NEW_START_PAGE_TOKEN" \
        --arg now "$(date -Iseconds)" \
        --arg prev_token "$PAGE_TOKEN" \
        '{page_token: $t, last_run: $now, prev_token: $prev_token}' \
        > "$STATE_FILE"
    echo "  State actualizado. Nuevo page_token: $NEW_START_PAGE_TOKEN" >> "$LOGFILE"
else
    echo "  WARN: no se obtuvo newStartPageToken. State sin cambiar." >> "$LOGFILE"
fi

# ────────────────────────────────────
# Step 7: Invocar Claude para emitir summary fact
# ────────────────────────────────────
IMPORTS_COUNT=$(jq '[.[] | select(.status == "imported")] | length' "$IMPORT_RESULTS_TMP")
ERRORS_COUNT=$(jq '[.[] | select(.status != "imported")] | length' "$IMPORT_RESULTS_TMP")

# Si no se importó nada y no hubo errores → log y salir sin invocar Claude
if [ "$IMPORTS_COUNT" -eq 0 ] && [ "$ERRORS_COUNT" -eq 0 ]; then
    echo "  Nada para importar este mes. Skipping Claude invocation." >> "$LOGFILE"
    rm -f "$IMPORT_RESULTS_TMP"
    echo "=== Rufino ingest-gdrive done (no-op): $(date) ===" >> "$LOGFILE"
    exit 0
fi

# Persistir resultados al raw dump para que Claude los lea
jq --slurpfile imports "$IMPORT_RESULTS_TMP" '. + {imports: $imports[0]}' "$RAW_FILE" > "${RAW_FILE}.tmp" && mv "${RAW_FILE}.tmp" "$RAW_FILE"
rm -f "$IMPORT_RESULTS_TMP"

RUFINO_DISPLAY_NAME="${RUFINO_DISPLAY_NAME:-el usuario}"
export RUFINO_VAULT_PATH RUFINO_DISPLAY_NAME
export RUFINO_GDRIVE_RAW_FILE="$RAW_FILE"
export RUFINO_GDRIVE_MONTH="$TARGET_MONTH"

PROMPT=$(envsubst '${RUFINO_VAULT_PATH} ${RUFINO_DISPLAY_NAME} ${RUFINO_GDRIVE_RAW_FILE} ${RUFINO_GDRIVE_MONTH}' < "$PROMPT_FILE")

"$CLAUDE" -p "$PROMPT" \
    --allowedTools "Read,Write,Edit,Glob,Grep,Bash" \
    --dangerously-skip-permissions \
    --model sonnet \
    >> "$LOGFILE" 2>&1

echo "=== Rufino ingest-gdrive done: $(date) ===" >> "$LOGFILE"
