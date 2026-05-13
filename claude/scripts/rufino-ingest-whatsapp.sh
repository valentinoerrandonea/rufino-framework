#!/bin/bash
# ─────────────────────────────────────────────────────────────
#  Rufino — WhatsApp ingestor
#  Weekly (Sundays 05:00). Procesá la semana ISO anterior:
#  levanta Puppeteer headless con `whatsapp-web.js` usando la
#  sesión persistida, fetchea chats + mensajes de la semana,
#  agrega counts + keywords (SIN texto literal), dumpea raw JSON
#  y delega a Claude la emisión de facts.
#
#  Cron schedule (después de browsing 03:30 + screentime 04:00 +
#  spotify 04:30):
#     Weekday=0  Hour=5  Minute=0
#
#  Requires:
#    - node, npm
#    - `~/.claude/whatsapp-ingestor/` con whatsapp-scrape.js + deps
#      (creado por `setup-whatsapp-auth.sh`)
#    - `~/.claude/whatsapp-session/` con sesión válida
#    - $RUFINO_VAULT_PATH set
# ─────────────────────────────────────────────────────────────
set -euo pipefail

LOGFILE="${RUFINO_LOG_DIR:-$HOME/.claude/logs/rufino}/rufino-ingest-whatsapp.log"
mkdir -p "$(dirname "$LOGFILE")"
PROMPT_FILE="$HOME/.claude/prompts/rufino-ingest-whatsapp.md"
CLAUDE="$(command -v claude || echo "$HOME/.local/bin/claude")"
VAULT_PATH="${RUFINO_VAULT_PATH:?RUFINO_VAULT_PATH must be set}"
LOCKFILE="$VAULT_PATH/_meta/.ingest-whatsapp.lock"

INGESTOR_DIR="$HOME/.claude/whatsapp-ingestor"
SESSION_DIR="$HOME/.claude/whatsapp-session"
SCRAPE_SCRIPT="$INGESTOR_DIR/whatsapp-scrape.js"

mkdir -p "$VAULT_PATH/_meta" "$VAULT_PATH/whatsapp/facts" "$VAULT_PATH/whatsapp/raw"

# Stale-lock-aware locking
if [ -f "$LOCKFILE" ]; then
    LOCK_PID=$(cat "$LOCKFILE" 2>/dev/null || echo "")
    if [ -n "$LOCK_PID" ] && kill -0 "$LOCK_PID" 2>/dev/null; then
        echo "=== Rufino ingest-whatsapp skipped: already running (PID $LOCK_PID) at $(date) ===" >> "$LOGFILE"
        exit 0
    fi
    rm -f "$LOCKFILE"
fi
echo "$$" > "$LOCKFILE"
trap 'rm -f "$LOCKFILE"' EXIT

echo "=== Rufino ingest-whatsapp run: $(date) ===" >> "$LOGFILE"

# ─── Sanity: deps ───
if ! command -v node >/dev/null 2>&1; then
    echo "ERROR: node no está instalado. brew install node, después correr setup-whatsapp-auth.sh." >> "$LOGFILE"
    exit 1
fi
if ! command -v jq >/dev/null 2>&1; then
    echo "ERROR: jq no está instalado." >> "$LOGFILE"
    exit 1
fi
if [ ! -f "$PROMPT_FILE" ]; then
    echo "ERROR: Prompt file not found at $PROMPT_FILE" >> "$LOGFILE"
    exit 1
fi
if [ ! -f "$SCRAPE_SCRIPT" ]; then
    echo "ERROR: $SCRAPE_SCRIPT no existe. Corré ~/.claude/scripts/setup-whatsapp-auth.sh primero." >> "$LOGFILE"
    exit 1
fi
if [ ! -d "$SESSION_DIR" ] || [ -z "$(ls -A "$SESSION_DIR" 2>/dev/null)" ]; then
    echo "ERROR: $SESSION_DIR vacío o no existe. Corré ~/.claude/scripts/setup-whatsapp-auth.sh primero." >> "$LOGFILE"
    exit 1
fi

# ────────────────────────────────────
# Step 1: Target ISO week (la semana ISO que acaba de cerrar)
# ────────────────────────────────────
if [ -n "${RUFINO_WHATSAPP_FORCE_WEEK:-}" ]; then
    TARGET_WEEK="$RUFINO_WHATSAPP_FORCE_WEEK"
else
    TARGET_WEEK="$(date -v-7d +%G-W%V)"
fi

ISO_YEAR="${TARGET_WEEK%-W*}"
ISO_WEEK="${TARGET_WEEK#*-W}"

read -r WEEK_START WEEK_END < <(python3 -c "
import datetime
y = int('$ISO_YEAR'); w = int('$ISO_WEEK')
monday = datetime.date.fromisocalendar(y, w, 1)
sunday = monday + datetime.timedelta(days=6)
print(monday.isoformat(), sunday.isoformat())
")

RAW_FILE="$VAULT_PATH/whatsapp/raw/${TARGET_WEEK}.json"

echo "  Week: $TARGET_WEEK ($WEEK_START → $WEEK_END)" >> "$LOGFILE"

# ────────────────────────────────────
# Step 2: Run scrape (Node + Puppeteer)
# ────────────────────────────────────
TMP_OUT=$(mktemp -t rufino-whatsapp-scrape-XXXXXX)
TMP_ERR=$(mktemp -t rufino-whatsapp-scrape-err-XXXXXX)
trap 'rm -f "$LOCKFILE" "$TMP_OUT" "$TMP_ERR"' EXIT

export RUFINO_WHATSAPP_SESSION_DIR="$SESSION_DIR"
export RUFINO_WHATSAPP_WEEK="$TARGET_WEEK"
export RUFINO_WHATSAPP_WEEK_START="$WEEK_START"
export RUFINO_WHATSAPP_WEEK_END="$WEEK_END"

echo "  Levantando Puppeteer + WhatsApp Web..." >> "$LOGFILE"

# Node script writes JSON to stdout, warns/errors to stderr.
# Wrap with timeout para evitar quedarse colgado (Puppeteer puede hangear si
# WhatsApp Web cambia algo). 6 min hard cap.
if ! ( cd "$INGESTOR_DIR" && /usr/bin/env node whatsapp-scrape.js ) > "$TMP_OUT" 2> "$TMP_ERR" ; then
    {
        echo "ERROR: whatsapp-scrape.js falló."
        echo "stderr:"
        cat "$TMP_ERR"
    } >> "$LOGFILE"
    exit 1
fi

# Pipe stderr warnings al log.
if [ -s "$TMP_ERR" ]; then
    {
        echo "  scrape stderr:"
        sed 's/^/    /' "$TMP_ERR"
    } >> "$LOGFILE"
fi

# Validar que el output sea JSON parseable.
if ! jq -e . "$TMP_OUT" >/dev/null 2>&1; then
    {
        echo "ERROR: whatsapp-scrape.js output no es JSON válido."
        echo "Primeras 50 líneas del output:"
        head -50 "$TMP_OUT"
    } >> "$LOGFILE"
    exit 1
fi

# Mover output al vault como raw.
cp "$TMP_OUT" "$RAW_FILE"

TOTAL_RECEIVED=$(jq -r '.total_received // 0' "$RAW_FILE")
TOTAL_SENT=$(jq -r '.total_sent // 0' "$RAW_FILE")
CHATS_ACTIVE=$(jq -r '.chats_active // 0' "$RAW_FILE")
TOTAL_MSGS=$((TOTAL_RECEIVED + TOTAL_SENT))

echo "  Mensajes recibidos: $TOTAL_RECEIVED | enviados: $TOTAL_SENT | chats activos: $CHATS_ACTIVE" >> "$LOGFILE"

# Privacy guard: si por error el raw incluyese texto literal,
# no avanzamos. Heurística: los campos esperados son metadata only.
if jq -e '..|.body? // empty | select(type=="string" and length > 0)' "$RAW_FILE" >/dev/null 2>&1; then
    echo "ERROR: raw JSON contiene campo 'body' con texto — privacy violation. Aborto." >> "$LOGFILE"
    rm -f "$RAW_FILE"
    exit 1
fi

# ────────────────────────────────────
# Step 3: Short-circuit si no hay actividad
# ────────────────────────────────────
if [ "$TOTAL_MSGS" -eq 0 ]; then
    echo "  No WhatsApp activity for $TARGET_WEEK. Skipping Claude invocation." >> "$LOGFILE"
    echo "=== Rufino ingest-whatsapp done (no-op): $(date) ===" >> "$LOGFILE"
    exit 0
fi

# ────────────────────────────────────
# Step 4: Invoke Claude
# ────────────────────────────────────
RUFINO_DISPLAY_NAME="${RUFINO_DISPLAY_NAME:-el usuario}"
export RUFINO_VAULT_PATH RUFINO_DISPLAY_NAME
export RUFINO_WHATSAPP_RAW_FILE="$RAW_FILE"

PROMPT=$(envsubst '${RUFINO_VAULT_PATH} ${RUFINO_DISPLAY_NAME} ${RUFINO_WHATSAPP_RAW_FILE} ${RUFINO_WHATSAPP_WEEK} ${RUFINO_WHATSAPP_WEEK_START} ${RUFINO_WHATSAPP_WEEK_END}' < "$PROMPT_FILE")

"$CLAUDE" -p "$PROMPT" \
    --allowedTools "Read,Write,Edit,Glob,Grep,Bash" \
    --dangerously-skip-permissions \
    --model sonnet \
    >> "$LOGFILE" 2>&1

echo "=== Rufino ingest-whatsapp done: $(date) ===" >> "$LOGFILE"
