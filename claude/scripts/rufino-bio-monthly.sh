#!/bin/bash
# ─────────────────────────────────────────────────────────────
#  Rufino — Bio mensual auto-update (Fase 5)
#  Día 1 del mes 06:00. Genera un snapshot tipo mini-CV/bio
#  derivado de perfil.md + facts recientes del vault.
#
#  Output:
#    ${RUFINO_VAULT_PATH}/general/bio/<YYYY-MM>.md
#
#  NO reemplaza perfil.md (es source-of-truth). Es solo un
#  snapshot "current state" del mes que Val puede copy-paste
#  a LinkedIn / intro a alguien nuevo / etc.
#
#  Override manual del mes target:
#    RUFINO_BIO_FORCE_MONTH=2026-05 bash ~/.claude/scripts/rufino-bio-monthly.sh
# ─────────────────────────────────────────────────────────────
set -euo pipefail

LOGFILE="${RUFINO_LOG_DIR:-$HOME/.claude/logs/rufino}/rufino-bio-monthly.log"
mkdir -p "$(dirname "$LOGFILE")"
PROMPT_FILE="$HOME/.claude/prompts/rufino-bio-monthly.md"
CLAUDE="$(command -v claude || echo "$HOME/.local/bin/claude")"
VAULT_PATH="${RUFINO_VAULT_PATH:?RUFINO_VAULT_PATH must be set}"
LOCKFILE="$VAULT_PATH/_meta/.bio-monthly.lock"

mkdir -p "$VAULT_PATH/_meta" "$VAULT_PATH/general/bio"

# Stale-lock-aware locking
if [ -f "$LOCKFILE" ]; then
    LOCK_PID=$(cat "$LOCKFILE" 2>/dev/null || echo "")
    if [ -n "$LOCK_PID" ] && kill -0 "$LOCK_PID" 2>/dev/null; then
        echo "=== Rufino bio-monthly skipped: already running (PID $LOCK_PID) at $(date) ===" >> "$LOGFILE"
        exit 0
    fi
    rm -f "$LOCKFILE"
fi
echo "$$" > "$LOCKFILE"
trap 'rm -f "$LOCKFILE"' EXIT

echo "=== Rufino bio-monthly run: $(date) ===" >> "$LOGFILE"

# ─── Sanity ───
if [ ! -f "$PROMPT_FILE" ]; then
    echo "ERROR: Prompt file not found at $PROMPT_FILE" >> "$LOGFILE"
    exit 1
fi
if [ ! -f "$VAULT_PATH/perfil.md" ]; then
    echo "ERROR: $VAULT_PATH/perfil.md no existe (source-of-truth). Abortando." >> "$LOGFILE"
    exit 1
fi

# ────────────────────────────────────
# Step 1: Target month
# ────────────────────────────────────
# Default: mes anterior (el cron corre día 1 a las 06:00, así que el
# mes que acaba de cerrar es el target). Override via
# RUFINO_BIO_FORCE_MONTH=YYYY-MM.
if [ -n "${RUFINO_BIO_FORCE_MONTH:-}" ]; then
    TARGET_MONTH="$RUFINO_BIO_FORCE_MONTH"
else
    # mes anterior — funciona en macOS BSD date
    TARGET_MONTH="$(date -v-1m +%Y-%m)"
fi

# Validar formato
if ! [[ "$TARGET_MONTH" =~ ^[0-9]{4}-[0-9]{2}$ ]]; then
    echo "ERROR: TARGET_MONTH inválido: '$TARGET_MONTH' (esperado YYYY-MM)" >> "$LOGFILE"
    exit 1
fi

MONTH_YEAR="${TARGET_MONTH%-*}"
MONTH_NUM="${TARGET_MONTH#*-}"

# Computar rango de fechas del mes para que el prompt filtre facts
MONTH_START="${TARGET_MONTH}-01"
# Último día del mes = primero del mes siguiente menos 1 día
MONTH_END=$(python3 -c "
import datetime, calendar
y = int('$MONTH_YEAR'); m = int('$MONTH_NUM')
last_day = calendar.monthrange(y, m)[1]
print(f'{y:04d}-{m:02d}-{last_day:02d}')
")

OUTPUT_FILE="$VAULT_PATH/general/bio/${TARGET_MONTH}.md"

echo "  Target month: $TARGET_MONTH ($MONTH_START → $MONTH_END)" >> "$LOGFILE"
echo "  Output: $OUTPUT_FILE" >> "$LOGFILE"

# ────────────────────────────────────
# Step 2: Invocar Claude
# ────────────────────────────────────
RUFINO_DISPLAY_NAME="${RUFINO_DISPLAY_NAME:-el usuario}"
export RUFINO_VAULT_PATH RUFINO_DISPLAY_NAME
export RUFINO_BIO_MONTH="$TARGET_MONTH"
export RUFINO_BIO_MONTH_START="$MONTH_START"
export RUFINO_BIO_MONTH_END="$MONTH_END"
export RUFINO_BIO_OUTPUT="$OUTPUT_FILE"

PROMPT=$(envsubst '${RUFINO_VAULT_PATH} ${RUFINO_DISPLAY_NAME} ${RUFINO_BIO_MONTH} ${RUFINO_BIO_MONTH_START} ${RUFINO_BIO_MONTH_END} ${RUFINO_BIO_OUTPUT}' < "$PROMPT_FILE")

"$CLAUDE" -p "$PROMPT" \
    --allowedTools "Read,Write,Edit,Glob,Grep,Bash" \
    --dangerously-skip-permissions \
    --model sonnet \
    >> "$LOGFILE" 2>&1

echo "=== Rufino bio-monthly done: $(date) ===" >> "$LOGFILE"
