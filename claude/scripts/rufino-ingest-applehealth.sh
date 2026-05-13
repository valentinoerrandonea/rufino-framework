#!/bin/bash
# ─────────────────────────────────────────────────────────────
#  Rufino — Apple Health ingestor (via iOS Shortcut → iCloud Drive)
#
#  Monthly (día 2 @ 06:00 local). Procesa el mes anterior. Lee los
#  JSONs que un Apple Shortcut programado del iPhone deja en la
#  carpeta `RufinoHealth/` de iCloud Drive (sincronizada al Mac).
#
#  El Shortcut corre 1 vez por día (recomendado 23:55) y escribe
#  4 archivos por jornada:
#
#    workouts-YYYY-MM-DD.json
#    sleep-YYYY-MM-DD.json
#    heart-rate-YYYY-MM-DD.json
#    steps-YYYY-MM-DD.json
#
#  Este wrapper:
#    1. Determina el mes target (default: mes anterior).
#    2. Agrupa todos los archivos del mes en un único JSON resumen.
#    3. Lo deja en `${RUFINO_VAULT_PATH}/applehealth/raw/<YYYY-MM>.json`.
#    4. Invoca Claude con el prompt de Apple Health.
#
#  Si la carpeta `RufinoHealth/` no existe o está vacía (Val aún
#  no armó el Shortcut), el script termina exit 0 con log claro —
#  NO error fatal. El cron mensual queda corriendo "vacío" hasta
#  que el Shortcut empiece a escribir.
#
#  Output:
#    Facts:     ${RUFINO_VAULT_PATH}/applehealth/facts/<slug>.md
#    Audit:     ${RUFINO_VAULT_PATH}/applehealth/raw/<YYYY-MM>.json
#
#  Override manual del mes:
#    RUFINO_APPLEHEALTH_FORCE_MONTH=2026-05 \
#      bash ~/.claude/scripts/rufino-ingest-applehealth.sh
#
#  Dependencias: jq (Homebrew), $RUFINO_VAULT_PATH set.
# ─────────────────────────────────────────────────────────────
set -euo pipefail

LOGFILE="${RUFINO_LOG_DIR:-$HOME/.claude/logs/rufino}/rufino-ingest-applehealth.log"
mkdir -p "$(dirname "$LOGFILE")"
PROMPT_FILE="$HOME/.claude/prompts/rufino-ingest-applehealth.md"
CLAUDE="$(command -v claude || echo "$HOME/.local/bin/claude")"
VAULT_PATH="${RUFINO_VAULT_PATH:?RUFINO_VAULT_PATH must be set}"
LOCKFILE="$VAULT_PATH/_meta/.ingest-applehealth.lock"

# Source: iCloud Drive folder donde el Shortcut iOS escribe.
ICLOUD_DIR="${RUFINO_APPLEHEALTH_DIR:-$HOME/Library/Mobile Documents/com~apple~CloudDocs/RufinoHealth}"

mkdir -p "$VAULT_PATH/_meta" "$VAULT_PATH/applehealth/facts" "$VAULT_PATH/applehealth/raw"

# Stale-lock-aware locking
if [ -f "$LOCKFILE" ]; then
    LOCK_PID=$(cat "$LOCKFILE" 2>/dev/null || echo "")
    if [ -n "$LOCK_PID" ] && kill -0 "$LOCK_PID" 2>/dev/null; then
        echo "=== Rufino ingest-applehealth skipped: already running (PID $LOCK_PID) at $(date) ===" >> "$LOGFILE"
        exit 0
    fi
    rm -f "$LOCKFILE"
fi
echo "$$" > "$LOCKFILE"
trap 'rm -f "$LOCKFILE"' EXIT

echo "=== Rufino ingest-applehealth run: $(date) ===" >> "$LOGFILE"

# ─── Sanity checks ───
if ! command -v jq >/dev/null 2>&1; then
    echo "ERROR: jq not installed (brew install jq)" >> "$LOGFILE"
    exit 1
fi
if [ ! -f "$PROMPT_FILE" ]; then
    echo "ERROR: Prompt file not found at $PROMPT_FILE" >> "$LOGFILE"
    exit 1
fi

# ────────────────────────────────────
# Step 1: Determinar mes target (default: mes anterior)
# ────────────────────────────────────
if [ -n "${RUFINO_APPLEHEALTH_FORCE_MONTH:-}" ]; then
    TARGET_MONTH="$RUFINO_APPLEHEALTH_FORCE_MONTH"
else
    # Mes anterior: día 1 del mes actual menos 1 día → ese mes.
    TARGET_MONTH=$(date -v1d -v-1d +%Y-%m)
fi

# Validar formato YYYY-MM
if ! [[ "$TARGET_MONTH" =~ ^[0-9]{4}-[0-9]{2}$ ]]; then
    echo "ERROR: TARGET_MONTH inválido: '$TARGET_MONTH' (esperado YYYY-MM)" >> "$LOGFILE"
    exit 1
fi

# Rango del mes para first_seen/last_seen
MONTH_START="${TARGET_MONTH}-01"
# Último día del mes: día 1 del mes siguiente menos 1 día.
MONTH_END=$(python3 -c "
import datetime
y, m = map(int, '$TARGET_MONTH'.split('-'))
if m == 12:
    nm = datetime.date(y + 1, 1, 1)
else:
    nm = datetime.date(y, m + 1, 1)
print((nm - datetime.timedelta(days=1)).isoformat())
")

echo "  Target month: $TARGET_MONTH ($MONTH_START → $MONTH_END)" >> "$LOGFILE"

# ────────────────────────────────────
# Step 2: Detectar carpeta de iCloud
# ────────────────────────────────────
if [ ! -d "$ICLOUD_DIR" ]; then
    cat >> "$LOGFILE" <<EOF
  No-op: la carpeta $ICLOUD_DIR no existe todavía.
  Val tiene que armar el Apple Shortcut iOS — ver docs/applehealth-notes.md.
  El cron mensual va a seguir corriendo vacío hasta que aparezcan archivos.
EOF
    echo "=== Rufino ingest-applehealth done (no-op, no folder): $(date) ===" >> "$LOGFILE"
    exit 0
fi

# ────────────────────────────────────
# Step 3: Listar archivos del mes target
# ────────────────────────────────────
# Patrón: <category>-YYYY-MM-DD.json donde categoria ∈ {workouts, sleep, heart-rate, steps}
# Glob: <cat>-<TARGET_MONTH>-*.json
TMP_LIST="$(mktemp -t rufino-applehealth-XXXXXX).list"
trap 'rm -f "$LOCKFILE" "$TMP_LIST"' EXIT

# Buscar archivos (en cada categoría) que matcheen el mes.
# find es más confiable que glob con espacios en el path.
find "$ICLOUD_DIR" -maxdepth 1 -type f -name "*-${TARGET_MONTH}-*.json" 2>/dev/null | sort > "$TMP_LIST"

NUM_FILES=$(wc -l < "$TMP_LIST" | tr -d ' ')
echo "  Found $NUM_FILES files for $TARGET_MONTH in $ICLOUD_DIR" >> "$LOGFILE"

if [ "$NUM_FILES" -eq 0 ]; then
    cat >> "$LOGFILE" <<EOF
  No-op: no hay archivos para $TARGET_MONTH en $ICLOUD_DIR.
  Posibles causas:
    - El Shortcut iOS todavía no está armado (ver docs/applehealth-notes.md).
    - El Shortcut está armado pero no corrió durante $TARGET_MONTH.
    - Los archivos están con otro patrón de nombre.
EOF
    echo "=== Rufino ingest-applehealth done (no-op, empty month): $(date) ===" >> "$LOGFILE"
    exit 0
fi

# ────────────────────────────────────
# Step 4: Agrupar archivos por categoría y validar JSON
# ────────────────────────────────────
TMP_DIR=$(mktemp -d -t rufino-applehealth-XXXXXX)
trap 'rm -f "$LOCKFILE" "$TMP_LIST"; rm -rf "$TMP_DIR"' EXIT

# Initialize empty arrays per categoría.
echo "[]" > "$TMP_DIR/workouts.json"
echo "[]" > "$TMP_DIR/sleep.json"
echo "[]" > "$TMP_DIR/heart-rate.json"
echo "[]" > "$TMP_DIR/steps.json"

SOURCES_JSON="$TMP_DIR/sources.json"
echo "[]" > "$SOURCES_JSON"

while IFS= read -r FILE; do
    [ -z "$FILE" ] && continue
    BASENAME=$(basename "$FILE")

    # Detectar categoría desde el prefijo del filename.
    # Patrón: <category>-YYYY-MM-DD.json donde category puede tener `-`.
    # Stripeamos `-YYYY-MM-DD.json` del final.
    CATEGORY=$(echo "$BASENAME" | sed -E 's/-[0-9]{4}-[0-9]{2}-[0-9]{2}\.json$//')

    case "$CATEGORY" in
        workouts|sleep|heart-rate|steps)
            ;;
        *)
            echo "  [skip] $BASENAME — categoría desconocida '$CATEGORY'" >> "$LOGFILE"
            continue
            ;;
    esac

    # Validar JSON.
    if ! jq empty "$FILE" 2>>"$LOGFILE"; then
        echo "  [warn] $BASENAME — JSON inválido, skipping" >> "$LOGFILE"
        continue
    fi

    # workouts.json es un array; el resto son objetos. Normalizamos
    # todo a arrays para append-friendly aggregation.
    BUCKET="$TMP_DIR/${CATEGORY}.json"
    TMP_MERGE="$TMP_DIR/.merge.$$"

    if [ "$CATEGORY" = "workouts" ]; then
        # Append items del array.
        jq -s '.[0] + (.[1] | if type == "array" then . else [.] end)' \
            "$BUCKET" "$FILE" > "$TMP_MERGE" 2>>"$LOGFILE" && mv "$TMP_MERGE" "$BUCKET"
    else
        # sleep / heart-rate / steps: objetos diarios → wrap como [obj] y append.
        jq -s '.[0] + (.[1] | if type == "array" then . else [.] end)' \
            "$BUCKET" "$FILE" > "$TMP_MERGE" 2>>"$LOGFILE" && mv "$TMP_MERGE" "$BUCKET"
    fi

    # Agregar al sources list (relative filename).
    jq --arg name "$BASENAME" '. + [$name]' "$SOURCES_JSON" > "${SOURCES_JSON}.tmp" \
        && mv "${SOURCES_JSON}.tmp" "$SOURCES_JSON"

done < "$TMP_LIST"

# ────────────────────────────────────
# Step 5: Counts por categoría
# ────────────────────────────────────
NUM_WORKOUTS=$(jq 'length' "$TMP_DIR/workouts.json")
NUM_SLEEP_DAYS=$(jq 'length' "$TMP_DIR/sleep.json")
NUM_HR_DAYS=$(jq 'length' "$TMP_DIR/heart-rate.json")
NUM_STEPS_DAYS=$(jq 'length' "$TMP_DIR/steps.json")

echo "  Workouts: $NUM_WORKOUTS  Sleep days: $NUM_SLEEP_DAYS  HR days: $NUM_HR_DAYS  Steps days: $NUM_STEPS_DAYS" >> "$LOGFILE"

TOTAL_RECORDS=$((NUM_WORKOUTS + NUM_SLEEP_DAYS + NUM_HR_DAYS + NUM_STEPS_DAYS))
if [ "$TOTAL_RECORDS" -eq 0 ]; then
    echo "  No-op: $NUM_FILES archivos encontrados pero ningún record válido tras parseo." >> "$LOGFILE"
    echo "=== Rufino ingest-applehealth done (no-op, empty after parse): $(date) ===" >> "$LOGFILE"
    exit 0
fi

# ────────────────────────────────────
# Step 6: Build raw aggregated JSON
# ────────────────────────────────────
RAW_FILE="$VAULT_PATH/applehealth/raw/${TARGET_MONTH}.json"

jq -n \
    --arg month "$TARGET_MONTH" \
    --arg month_start "$MONTH_START" \
    --arg month_end "$MONTH_END" \
    --argjson workouts "$(cat "$TMP_DIR/workouts.json")" \
    --argjson sleep "$(cat "$TMP_DIR/sleep.json")" \
    --argjson hr "$(cat "$TMP_DIR/heart-rate.json")" \
    --argjson steps "$(cat "$TMP_DIR/steps.json")" \
    --argjson sources "$(cat "$SOURCES_JSON")" \
    '{
      month: $month,
      month_start: $month_start,
      month_end: $month_end,
      sources: $sources,
      counts: {
        workouts: ($workouts | length),
        sleep_days: ($sleep | length),
        heart_rate_days: ($hr | length),
        steps_days: ($steps | length)
      },
      workouts: $workouts,
      sleep: $sleep,
      heart_rate: $hr,
      steps: $steps
    }' > "$RAW_FILE"

echo "  Raw aggregated → $RAW_FILE" >> "$LOGFILE"

# ────────────────────────────────────
# Step 7: Invocar Claude con el prompt
# ────────────────────────────────────
RUFINO_DISPLAY_NAME="${RUFINO_DISPLAY_NAME:-el usuario}"
export RUFINO_VAULT_PATH RUFINO_DISPLAY_NAME
export RUFINO_APPLEHEALTH_RAW_FILE="$RAW_FILE"
export RUFINO_APPLEHEALTH_MONTH="$TARGET_MONTH"
export RUFINO_APPLEHEALTH_MONTH_START="$MONTH_START"
export RUFINO_APPLEHEALTH_MONTH_END="$MONTH_END"

PROMPT=$(envsubst '${RUFINO_VAULT_PATH} ${RUFINO_DISPLAY_NAME} ${RUFINO_APPLEHEALTH_RAW_FILE} ${RUFINO_APPLEHEALTH_MONTH} ${RUFINO_APPLEHEALTH_MONTH_START} ${RUFINO_APPLEHEALTH_MONTH_END}' < "$PROMPT_FILE")

"$CLAUDE" -p "$PROMPT" \
    --allowedTools "Read,Write,Edit,Glob,Grep,Bash" \
    --dangerously-skip-permissions \
    --model sonnet \
    >> "$LOGFILE" 2>&1

echo "=== Rufino ingest-applehealth done: $(date) ===" >> "$LOGFILE"
