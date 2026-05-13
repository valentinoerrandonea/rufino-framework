#!/bin/bash
# ─────────────────────────────────────────────────────────────
#  Rufino — YouTube watch history ingestor (vía Google Takeout)
#
#  Monthly (day 5 @ 05:30 local). Detecta ZIPs nuevos de Google
#  Takeout en Drive (export bimestral configurado por Val),
#  baja los nuevos, parsea `historial-de-reproducciones.json` (o
#  `watch-history.json` en inglés), y emite facts agregados de
#  los 2 meses cubiertos.
#
#  Output:
#    Facts:     ${RUFINO_VAULT_PATH}/youtube/facts/<slug>.md
#    Audit:     ${RUFINO_VAULT_PATH}/youtube/raw/<YYYY-MM>.json
#    State:     ${RUFINO_VAULT_PATH}/youtube/.state (last_run_iso,
#               last_processed_takeout_ids[])
#
#  Como el export es cada 2 meses pero el cron es mensual, la
#  mitad de las corridas son no-op (no hay ZIP nuevo). OK.
#
#  Dependencias:
#    - OAuth GDrive (mismo refresh token que el ingestor gdrive-ingestor:
#      `rufino-gdrive-refresh-token` en Keychain).
#    - `jq`, `curl`, `unzip` (built-in macOS / Homebrew).
#    - $RUFINO_VAULT_PATH set.
# ─────────────────────────────────────────────────────────────
set -euo pipefail

LOGFILE="${RUFINO_LOG_DIR:-$HOME/.claude/logs/rufino}/rufino-ingest-youtube.log"
mkdir -p "$(dirname "$LOGFILE")"
PROMPT_FILE="$HOME/.claude/prompts/rufino-ingest-youtube.md"
CLAUDE="$(command -v claude || echo "$HOME/.local/bin/claude")"
VAULT_PATH="${RUFINO_VAULT_PATH:?RUFINO_VAULT_PATH must be set}"
LOCKFILE="$VAULT_PATH/_meta/.ingest-youtube.lock"
STATE_FILE="$VAULT_PATH/youtube/.state"

# OAuth secrets (todos compartidos con gdrive-ingestor)
KEYCHAIN_REFRESH="rufino-gdrive-refresh-token"
KEYCHAIN_CLIENT_ID="rufino-gdrive-client-id"
KEYCHAIN_CLIENT_SECRET="rufino-gdrive-client-secret"

mkdir -p "$VAULT_PATH/_meta" "$VAULT_PATH/youtube/facts" "$VAULT_PATH/youtube/raw"

# Stale-lock-aware locking
if [ -f "$LOCKFILE" ]; then
    LOCK_PID=$(cat "$LOCKFILE" 2>/dev/null || echo "")
    if [ -n "$LOCK_PID" ] && kill -0 "$LOCK_PID" 2>/dev/null; then
        echo "=== Rufino ingest-youtube skipped: already running (PID $LOCK_PID) at $(date) ===" >> "$LOGFILE"
        exit 0
    fi
    rm -f "$LOCKFILE"
fi
echo "$$" > "$LOCKFILE"
trap 'rm -f "$LOCKFILE"' EXIT

echo "=== Rufino ingest-youtube run: $(date) ===" >> "$LOGFILE"

# ─── Sanity checks ───
for bin in jq curl unzip security; do
    if ! command -v "$bin" >/dev/null 2>&1; then
        echo "ERROR: $bin not installed" >> "$LOGFILE"
        exit 1
    fi
done
if [ ! -f "$PROMPT_FILE" ]; then
    echo "ERROR: Prompt file not found at $PROMPT_FILE" >> "$LOGFILE"
    exit 1
fi

# ────────────────────────────────────
# Step 1: Recuperar refresh token (compartido con gdrive-ingestor)
# ────────────────────────────────────
REFRESH_TOKEN=$(security find-generic-password -s "$KEYCHAIN_REFRESH" -a val -w 2>/dev/null || true)
if [ -z "$REFRESH_TOKEN" ]; then
    cat >> "$LOGFILE" <<EOF
ERROR: GDrive OAuth no configurado.
       Falta el secret '$KEYCHAIN_REFRESH' en el Keychain.
       Setup: el cron de YouTube reusa el refresh token del ingestor gdrive.
       Corré primero: bash ~/.claude/scripts/setup-gdrive-auth.sh
       (provisto por el agente gdrive-ingestor).
EOF
    exit 1
fi

CLIENT_ID=$(security find-generic-password -s "$KEYCHAIN_CLIENT_ID" -a val -w 2>/dev/null || true)
CLIENT_SECRET=$(security find-generic-password -s "$KEYCHAIN_CLIENT_SECRET" -a val -w 2>/dev/null || true)
if [ -z "$CLIENT_ID" ] || [ -z "$CLIENT_SECRET" ]; then
    echo "ERROR: faltan client_id / client_secret en Keychain (gdrive-ingestor setup)." >> "$LOGFILE"
    exit 1
fi

# ────────────────────────────────────
# Step 2: Refresh → access token
# ────────────────────────────────────
ACCESS_TOKEN=$(curl -fsS -X POST "https://oauth2.googleapis.com/token" \
    -d "client_id=$CLIENT_ID" \
    -d "client_secret=$CLIENT_SECRET" \
    -d "refresh_token=$REFRESH_TOKEN" \
    -d "grant_type=refresh_token" 2>>"$LOGFILE" | jq -r '.access_token // empty')

if [ -z "$ACCESS_TOKEN" ]; then
    echo "ERROR: no se pudo obtener access_token desde refresh_token." >> "$LOGFILE"
    exit 1
fi

# ────────────────────────────────────
# Step 3: Leer state (last_run_iso, processed ids)
# ────────────────────────────────────
if [ -f "$STATE_FILE" ]; then
    LAST_RUN_ISO=$(jq -r '.last_run_iso // ""' "$STATE_FILE" 2>/dev/null || echo "")
    PROCESSED_IDS=$(jq -r '.last_processed_takeout_ids // [] | join(",")' "$STATE_FILE" 2>/dev/null || echo "")
else
    LAST_RUN_ISO=""
    PROCESSED_IDS=""
fi

# Default: si nunca corrió, mirá los últimos 70 días (un poco más que 2 meses).
if [ -z "$LAST_RUN_ISO" ]; then
    LAST_RUN_ISO=$(date -u -v-70d +"%Y-%m-%dT%H:%M:%SZ")
fi

NOW_ISO=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
echo "  Cutoff: createdTime > $LAST_RUN_ISO" >> "$LOGFILE"

# ────────────────────────────────────
# Step 4: List Drive — buscar ZIPs de Takeout nuevos
# ────────────────────────────────────
# Query: nombre contiene 'takeout', mime zip, no en trash, creado después del último run.
# Google pone los exports en `Takeout/` por default, con nombres tipo
# `takeout-20260506T053012Z-001.zip` (puede haber multi-part si supera el size).
QUERY="name contains 'takeout' and mimeType='application/zip' and trashed=false and createdTime > '$LAST_RUN_ISO'"
QUERY_ENC=$(jq -rn --arg q "$QUERY" '$q|@uri')

LIST_JSON=$(curl -fsS \
    -H "Authorization: Bearer $ACCESS_TOKEN" \
    "https://www.googleapis.com/drive/v3/files?q=$QUERY_ENC&fields=files(id,name,createdTime,size,mimeType)&pageSize=100&orderBy=createdTime" \
    2>>"$LOGFILE")

NUM_NEW=$(echo "$LIST_JSON" | jq '.files | length')
echo "  Drive listing: $NUM_NEW ZIPs candidatos" >> "$LOGFILE"

if [ "$NUM_NEW" -eq 0 ]; then
    echo "  No-op: no hay ZIPs nuevos de Takeout (esperado en meses sin export bimestral)." >> "$LOGFILE"
    # Igual actualizamos last_run_iso para no re-listar lo viejo la próxima vez.
    jq -n --arg now "$NOW_ISO" \
          --argjson ids "$(echo "$PROCESSED_IDS" | jq -Rcn '[inputs | split(",")[] | select(length>0)]')" \
          '{ last_run_iso: $now, last_processed_takeout_ids: $ids }' > "$STATE_FILE"
    echo "=== Rufino ingest-youtube done (no-op): $(date) ===" >> "$LOGFILE"
    exit 0
fi

# ────────────────────────────────────
# Step 5: Para cada ZIP nuevo: download → unzip → extraer watch-history.json
# ────────────────────────────────────
TMP_BASE="$(mktemp -d -t rufino-youtube-XXXXXX)"
trap 'rm -f "$LOCKFILE"; rm -rf "$TMP_BASE"' EXIT

PROCESSED_THIS_RUN=()
EXTRACTED_FILES=()

# Itero los archivos en orden cronológico (orderBy=createdTime ya lo hace).
NUM_FILES=$(echo "$LIST_JSON" | jq '.files | length')
for i in $(seq 0 $((NUM_FILES - 1))); do
    FILE_ID=$(echo "$LIST_JSON"   | jq -r ".files[$i].id")
    FILE_NAME=$(echo "$LIST_JSON" | jq -r ".files[$i].name")
    FILE_CREATED=$(echo "$LIST_JSON" | jq -r ".files[$i].createdTime")

    # Idempotencia: si ya está en processed_ids, skip.
    if [[ ",$PROCESSED_IDS," == *",$FILE_ID,"* ]]; then
        echo "  [skip] $FILE_NAME ($FILE_ID) ya procesado." >> "$LOGFILE"
        continue
    fi

    # Filtrar nombres que claramente no son del export de YouTube. Heurística defensiva:
    # los exports de Takeout configurados solo con "YouTube and YouTube Music" llegan
    # como `takeout-<timestamp>-NNN.zip` y no anuncian YouTube en el filename.
    # NO filtramos por nombre — confiamos en que el setup es el del prompt.

    ZIP_PATH="$TMP_BASE/$FILE_NAME"
    UNZIP_DIR="$TMP_BASE/unzipped-$FILE_ID"
    mkdir -p "$UNZIP_DIR"

    echo "  [download] $FILE_NAME ($FILE_ID, $FILE_CREATED)" >> "$LOGFILE"
    if ! curl -fsSL \
            -H "Authorization: Bearer $ACCESS_TOKEN" \
            -o "$ZIP_PATH" \
            "https://www.googleapis.com/drive/v3/files/$FILE_ID?alt=media" \
            2>>"$LOGFILE"; then
        echo "  [error] download failed for $FILE_NAME — skipping" >> "$LOGFILE"
        continue
    fi

    # Unzip silencioso
    if ! unzip -q -o "$ZIP_PATH" -d "$UNZIP_DIR" 2>>"$LOGFILE"; then
        echo "  [warn] unzip failed for $FILE_NAME — skipping (¿corrupto / multi-part?)" >> "$LOGFILE"
        rm -f "$ZIP_PATH"
        rm -rf "$UNZIP_DIR"
        continue
    fi

    # Buscar el watch-history.json (puede ser en ES o EN, varios paths).
    HISTORY_FILE=$(find "$UNZIP_DIR" -type f \( \
            -name 'historial-de-reproducciones.json' \
            -o -name 'watch-history.json' \
            -o -name 'Historial-de-reproducciones.json' \
        \) 2>/dev/null | head -1)

    if [ -z "$HISTORY_FILE" ] || [ ! -f "$HISTORY_FILE" ]; then
        echo "  [skip] $FILE_NAME no contiene watch-history.json (probablemente ZIP de otra cuenta o multi-part sin historial)." >> "$LOGFILE"
        rm -f "$ZIP_PATH"
        rm -rf "$UNZIP_DIR"
        # Marcamos como procesado para no re-bajarlo cada mes.
        PROCESSED_THIS_RUN+=("$FILE_ID")
        continue
    fi

    # Validar JSON antes de copiar.
    if ! jq empty "$HISTORY_FILE" 2>>"$LOGFILE"; then
        echo "  [error] $HISTORY_FILE no es JSON válido — skipping." >> "$LOGFILE"
        rm -f "$ZIP_PATH"
        rm -rf "$UNZIP_DIR"
        continue
    fi

    # Determinar etiqueta del periodo: tomamos el rango de fechas que cubre el JSON.
    # El export bimestral cubre ~2 meses; el filename principal es por mes del export.
    EXPORT_MONTH=$(date -u -j -f "%Y-%m-%dT%H:%M:%S" "${FILE_CREATED%.*}" +"%Y-%m" 2>/dev/null || date -u +"%Y-%m")
    DEST_RAW="$VAULT_PATH/youtube/raw/${EXPORT_MONTH}.json"

    # Si ya existe (rara colisión con multi-part del mismo export), append-merge.
    if [ -f "$DEST_RAW" ]; then
        MERGED="$TMP_BASE/merged-${FILE_ID}.json"
        jq -s 'add | unique_by(.time + (.titleUrl // ""))' "$DEST_RAW" "$HISTORY_FILE" > "$MERGED" 2>>"$LOGFILE" || cp "$HISTORY_FILE" "$MERGED"
        cp "$MERGED" "$DEST_RAW"
    else
        cp "$HISTORY_FILE" "$DEST_RAW"
    fi

    EXTRACTED_FILES+=("$DEST_RAW")
    PROCESSED_THIS_RUN+=("$FILE_ID")
    echo "  [ok] $FILE_NAME → $DEST_RAW" >> "$LOGFILE"

    # Cleanup inmediato del tmp para no inflar /tmp con un export de 2GB.
    rm -f "$ZIP_PATH"
    rm -rf "$UNZIP_DIR"
done

if [ "${#EXTRACTED_FILES[@]}" -eq 0 ]; then
    echo "  No-op tras filtrar: no se extrajo ningún watch-history.json." >> "$LOGFILE"
    # Igual actualizamos state.
    MERGED_IDS=$(printf '%s\n' "$PROCESSED_IDS" "$(IFS=,; echo "${PROCESSED_THIS_RUN[*]:-}")" \
        | tr ',' '\n' | sed '/^$/d' | sort -u | paste -sd, -)
    jq -n --arg now "$NOW_ISO" \
          --argjson ids "$(echo "$MERGED_IDS" | jq -Rcn '[inputs | split(",")[] | select(length>0)]')" \
          '{ last_run_iso: $now, last_processed_takeout_ids: $ids }' > "$STATE_FILE"
    echo "=== Rufino ingest-youtube done (no-op): $(date) ===" >> "$LOGFILE"
    exit 0
fi

# ────────────────────────────────────
# Step 6: Update state file
# ────────────────────────────────────
MERGED_IDS=$(printf '%s\n' "$PROCESSED_IDS" "$(IFS=,; echo "${PROCESSED_THIS_RUN[*]:-}")" \
    | tr ',' '\n' | sed '/^$/d' | sort -u | paste -sd, -)
jq -n --arg now "$NOW_ISO" \
      --argjson ids "$(echo "$MERGED_IDS" | jq -Rcn '[inputs | split(",")[] | select(length>0)]')" \
      '{ last_run_iso: $now, last_processed_takeout_ids: $ids }' > "$STATE_FILE"

# ────────────────────────────────────
# Step 7: Invocar Claude — uno por archivo extraído
# ────────────────────────────────────
RUFINO_DISPLAY_NAME="${RUFINO_DISPLAY_NAME:-el usuario}"
export RUFINO_VAULT_PATH RUFINO_DISPLAY_NAME

for RAW_FILE in "${EXTRACTED_FILES[@]}"; do
    EXPORT_MONTH=$(basename "$RAW_FILE" .json)   # ej "2026-05"
    export RUFINO_YOUTUBE_RAW_FILE="$RAW_FILE"
    export RUFINO_YOUTUBE_EXPORT_MONTH="$EXPORT_MONTH"

    # Detectar rango temporal real del JSON (min/max de .time)
    DATE_MIN=$(jq -r '[.[].time] | min // ""' "$RAW_FILE" 2>/dev/null | cut -c1-10)
    DATE_MAX=$(jq -r '[.[].time] | max // ""' "$RAW_FILE" 2>/dev/null | cut -c1-10)
    export RUFINO_YOUTUBE_DATE_MIN="${DATE_MIN:-$EXPORT_MONTH-01}"
    export RUFINO_YOUTUBE_DATE_MAX="${DATE_MAX:-$EXPORT_MONTH-28}"

    echo "  [claude] processing $EXPORT_MONTH ($RUFINO_YOUTUBE_DATE_MIN → $RUFINO_YOUTUBE_DATE_MAX)" >> "$LOGFILE"

    PROMPT=$(envsubst '${RUFINO_VAULT_PATH} ${RUFINO_DISPLAY_NAME} ${RUFINO_YOUTUBE_RAW_FILE} ${RUFINO_YOUTUBE_EXPORT_MONTH} ${RUFINO_YOUTUBE_DATE_MIN} ${RUFINO_YOUTUBE_DATE_MAX}' < "$PROMPT_FILE")

    "$CLAUDE" -p "$PROMPT" \
        --allowedTools "Read,Write,Edit,Glob,Grep,Bash" \
        --dangerously-skip-permissions \
        --model sonnet \
        >> "$LOGFILE" 2>&1
done

echo "=== Rufino ingest-youtube done: $(date) ===" >> "$LOGFILE"
