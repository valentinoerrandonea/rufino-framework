#!/bin/bash
# ─────────────────────────────────────────────────────────────
#  Rufino — WhatsApp backfill (one-shot, último año por default)
#
#  Levanta whatsapp-web.js con sesión persistida, fetchea CHATS
#  ENTEROS (hasta `RUFINO_WHATSAPP_FETCH_LIMIT` = 5000 default),
#  filtra por el período pedido, agrega counts + keywords sin
#  texto literal, y dumpea a `$VAULT_PATH/whatsapp/raw/backfill-<since>-<until>.json`.
#  Después invoca a Claude para emitir facts anuales agregados.
#
#  Reglas (Val 2026-05-13):
#    - Excluye 3 grupos puntuales por nombre.
#    - Solo chats con >= 100 mensajes son "BUENOS".
#    - Default período: últimos 12 meses.
#
#  Uso:
#    RUFINO_VAULT_PATH=/path/to/vault \
#    bash ~/.claude/scripts/rufino-ingest-whatsapp-backfill.sh
#
#  Overrides:
#    RUFINO_WHATSAPP_BACKFILL_SINCE=2025-05-13   (default: hace 12 meses)
#    RUFINO_WHATSAPP_BACKFILL_UNTIL=2026-05-13   (default: hoy)
#    RUFINO_WHATSAPP_MIN_MESSAGES=100             (default 100)
#    RUFINO_WHATSAPP_FETCH_LIMIT=5000             (default 5000)
# ─────────────────────────────────────────────────────────────
set -euo pipefail

LOGFILE="${RUFINO_LOG_DIR:-$HOME/.claude/logs/rufino}/rufino-ingest-whatsapp-backfill.log"
mkdir -p "$(dirname "$LOGFILE")"
PROMPT_FILE="$HOME/.claude/prompts/rufino-ingest-whatsapp.md"
CLAUDE="$(command -v claude || echo "$HOME/.local/bin/claude")"
VAULT_PATH="${RUFINO_VAULT_PATH:?RUFINO_VAULT_PATH must be set}"

INGESTOR_DIR="$HOME/.claude/whatsapp-ingestor"
SESSION_DIR="$HOME/.claude/whatsapp-session"
SCRAPE_SCRIPT="$INGESTOR_DIR/whatsapp-scrape.js"

mkdir -p "$VAULT_PATH/whatsapp/facts" "$VAULT_PATH/whatsapp/raw"

echo "=== Rufino whatsapp-backfill: $(date) ===" >> "$LOGFILE"

# Sanity
[ -f "$SCRAPE_SCRIPT" ] || { echo "ERROR: $SCRAPE_SCRIPT missing. Run setup-whatsapp-auth.sh first." >> "$LOGFILE"; exit 1; }
[ -d "$SESSION_DIR" ] && [ -n "$(ls -A "$SESSION_DIR" 2>/dev/null)" ] || { echo "ERROR: WhatsApp session missing. Re-run setup-whatsapp-auth.sh." >> "$LOGFILE"; exit 1; }
command -v node >/dev/null 2>&1 || { echo "ERROR: node not installed" >> "$LOGFILE"; exit 1; }
command -v jq >/dev/null 2>&1 || { echo "ERROR: jq not installed" >> "$LOGFILE"; exit 1; }

SINCE="${RUFINO_WHATSAPP_BACKFILL_SINCE:-$(date -v-12m +%Y-%m-%d)}"
UNTIL="${RUFINO_WHATSAPP_BACKFILL_UNTIL:-$(date +%Y-%m-%d)}"
PERIOD_LABEL="backfill-${SINCE}-to-${UNTIL}"
RAW_FILE="$VAULT_PATH/whatsapp/raw/${PERIOD_LABEL}.json"

echo "  Period: $SINCE → $UNTIL" >> "$LOGFILE"

# Reglas de Val:
export RUFINO_WHATSAPP_EXCLUDED_GROUPS='["BLESSED VLLC","Fechitas 💣 | Crobar ⛓️| Mandarine🍊| Mute 🏝️| The Bow🪭 | Rio 🦩🌿","Nicolás Grimaldi - eventos [2]"]'
export RUFINO_WHATSAPP_MIN_MESSAGES="${RUFINO_WHATSAPP_MIN_MESSAGES:-100}"
export RUFINO_WHATSAPP_FETCH_LIMIT="${RUFINO_WHATSAPP_FETCH_LIMIT:-5000}"
export RUFINO_WHATSAPP_TOP_N="${RUFINO_WHATSAPP_TOP_N:-30}"

# Período via PERIOD_*
export RUFINO_WHATSAPP_SESSION_DIR="$SESSION_DIR"
export RUFINO_WHATSAPP_PERIOD_LABEL="$PERIOD_LABEL"
export RUFINO_WHATSAPP_PERIOD_START="$SINCE"
export RUFINO_WHATSAPP_PERIOD_END="$UNTIL"

# Run scrape (sin lock global porque el lock del cron normal podría conflictuar)
TMP_OUT=$(mktemp -t rufino-whatsapp-backfill-XXXXXX)
TMP_ERR=$(mktemp -t rufino-whatsapp-backfill-err-XXXXXX)
trap 'rm -f "$TMP_OUT" "$TMP_ERR"' EXIT

echo "  Levantando Puppeteer + whatsapp-web.js (fetch_limit=$RUFINO_WHATSAPP_FETCH_LIMIT, min_messages=$RUFINO_WHATSAPP_MIN_MESSAGES)..." >> "$LOGFILE"
echo "  Esto puede tardar varios minutos (fetch de muchos mensajes por chat)..." >> "$LOGFILE"

if ! ( cd "$INGESTOR_DIR" && /usr/bin/env node whatsapp-scrape.js ) > "$TMP_OUT" 2> "$TMP_ERR" ; then
    { echo "ERROR: whatsapp-scrape.js falló (backfill)."; echo "stderr:"; cat "$TMP_ERR"; } >> "$LOGFILE"
    exit 1
fi

if [ -s "$TMP_ERR" ]; then
    { echo "  scrape stderr (groups excluidos + under-threshold skips):"; sed 's/^/    /' "$TMP_ERR"; } >> "$LOGFILE"
fi

# Validate JSON
if ! jq -e . "$TMP_OUT" >/dev/null 2>&1; then
    { echo "ERROR: scrape output no es JSON válido."; head -50 "$TMP_OUT"; } >> "$LOGFILE"
    exit 1
fi

# Privacy guard
if jq -e '..|.body? // empty | select(type=="string" and length > 0)' "$TMP_OUT" >/dev/null 2>&1; then
    echo "ERROR: raw JSON contiene 'body' con texto literal — privacy violation." >> "$LOGFILE"
    exit 1
fi

cp "$TMP_OUT" "$RAW_FILE"

TOTAL_RECEIVED=$(jq -r '.total_received // 0' "$RAW_FILE")
TOTAL_SENT=$(jq -r '.total_sent // 0' "$RAW_FILE")
CHATS_ACTIVE=$(jq -r '.chats_active // 0' "$RAW_FILE")
TOTAL_MSGS=$((TOTAL_RECEIVED + TOTAL_SENT))

echo "  Mensajes recibidos: $TOTAL_RECEIVED | enviados: $TOTAL_SENT | chats activos: $CHATS_ACTIVE" >> "$LOGFILE"

if [ "$TOTAL_MSGS" -eq 0 ]; then
    echo "  No data en el período. ¿WhatsApp Web todavía sincronizando? Esperá unos minutos y re-corré." >> "$LOGFILE"
    exit 0
fi

# Invoke Claude — reusa el prompt semanal pero con período custom.
# El prompt va a generar facts con external_ref.type adecuado al período.
RUFINO_DISPLAY_NAME="${RUFINO_DISPLAY_NAME:-el usuario}"
export RUFINO_VAULT_PATH RUFINO_DISPLAY_NAME
export RUFINO_WHATSAPP_RAW_FILE="$RAW_FILE"
export RUFINO_WHATSAPP_WEEK="$PERIOD_LABEL"
export RUFINO_WHATSAPP_WEEK_START="$SINCE"
export RUFINO_WHATSAPP_WEEK_END="$UNTIL"

PROMPT=$(envsubst '${RUFINO_VAULT_PATH} ${RUFINO_DISPLAY_NAME} ${RUFINO_WHATSAPP_RAW_FILE} ${RUFINO_WHATSAPP_WEEK} ${RUFINO_WHATSAPP_WEEK_START} ${RUFINO_WHATSAPP_WEEK_END}' < "$PROMPT_FILE")

"$CLAUDE" -p "$PROMPT" \
    --allowedTools "Read,Write,Edit,Glob,Grep,Bash" \
    --dangerously-skip-permissions \
    --model sonnet \
    >> "$LOGFILE" 2>&1

echo "=== Rufino whatsapp-backfill done: $(date) ===" >> "$LOGFILE"
echo "Backfill listo. Facts en \$RUFINO_VAULT_PATH/whatsapp/facts/"
