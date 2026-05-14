#!/bin/bash
# ─────────────────────────────────────────────────────────────
#  Rufino — Weekly digest
#  Cron viernes 18:00 (LaunchAgent com.user.rufino-digest-weekly).
#  Sintetiza la semana ISO anterior en un digest narrativo y lo
#  manda por email a Val.
#
#  Reads:
#    - Facts de los últimos 7 días en ${RUFINO_VAULT_PATH}/<src>/facts/
#      (github, calendar, screentime, browsing, spotify, gdrive,
#      youtube, whatsapp)
#    - Notas modificadas en los últimos 7 días: sesion*, decision*,
#      aprendizaje* bajo proyectos/, rufino/, sesiones/
#    - Pendientes activos: ${RUFINO_VAULT_PATH}/rufino/_pendientes.md
#    - Questions pending: ${RUFINO_VAULT_PATH}/questions/
#
#  Writes:
#    - ${RUFINO_VAULT_PATH}/general/digests/<YYYY-WW>.md
#    - Email a valentinoerrandonea2002@gmail.com (a menos que dry-run)
#
#  Env vars:
#    - RUFINO_VAULT_PATH (requerido)
#    - RUFINO_DISPLAY_NAME (default: "Val")
#    - RUFINO_DIGEST_FORCE_WEEK (opcional, ej "2026-W19") — override
#      de la semana target. Default: semana ISO ANTERIOR a la fecha
#      de corrida (viernes corre con la semana anterior cerrada).
#    - RUFINO_DIGEST_DRY_RUN=1 → escribe el digest pero NO manda email.
# ─────────────────────────────────────────────────────────────
set -euo pipefail

LOGFILE="${RUFINO_LOG_DIR:-$HOME/.claude/logs/rufino}/rufino-digest-weekly.log"
mkdir -p "$(dirname "$LOGFILE")"
PROMPT_FILE="$HOME/.claude/prompts/rufino-digest-weekly.md"
CLAUDE="$(command -v claude || echo "$HOME/.local/bin/claude")"
VAULT_PATH="${RUFINO_VAULT_PATH:?RUFINO_VAULT_PATH must be set}"
LOCKFILE="$VAULT_PATH/_meta/.digest-weekly.lock"

mkdir -p "$VAULT_PATH/_meta" "$VAULT_PATH/general/digests"

# Stale-lock-aware locking
if [ -f "$LOCKFILE" ]; then
    LOCK_PID=$(cat "$LOCKFILE" 2>/dev/null || echo "")
    if [ -n "$LOCK_PID" ] && kill -0 "$LOCK_PID" 2>/dev/null; then
        echo "=== Rufino digest-weekly skipped: already running (PID $LOCK_PID) at $(date) ===" >> "$LOGFILE"
        exit 0
    fi
    rm -f "$LOCKFILE"
fi
echo "$$" > "$LOCKFILE"
trap 'rm -f "$LOCKFILE"' EXIT

echo "=== Rufino digest-weekly run: $(date) ===" >> "$LOGFILE"

# Sanity
if [ ! -x "$CLAUDE" ] && ! command -v claude >/dev/null 2>&1; then
    echo "ERROR: claude CLI no encontrado" >> "$LOGFILE"
    exit 1
fi
if [ ! -f "$PROMPT_FILE" ]; then
    echo "ERROR: Prompt file no encontrado en $PROMPT_FILE" >> "$LOGFILE"
    exit 1
fi
if ! command -v envsubst >/dev/null 2>&1; then
    echo "ERROR: envsubst no instalado (brew install gettext)" >> "$LOGFILE"
    exit 1
fi

# ────────────────────────────────────
# Step 1: Calcular la semana target
# ────────────────────────────────────
# Default: si corremos un viernes 18:00, queremos la semana CORRIENTE
# que termina ese viernes (lunes → viernes recién cerrados).
# Implementación: tomá el viernes más reciente <= hoy, y computá la
# semana ISO de ese viernes.
#
# Si RUFINO_DIGEST_FORCE_WEEK está seteada (formato YYYY-Wxx), usá esa.

if [ -n "${RUFINO_DIGEST_FORCE_WEEK:-}" ]; then
    TARGET_WEEK="$RUFINO_DIGEST_FORCE_WEEK"
    # Validar formato YYYY-Wxx
    if ! [[ "$TARGET_WEEK" =~ ^[0-9]{4}-W[0-9]{2}$ ]]; then
        echo "ERROR: RUFINO_DIGEST_FORCE_WEEK formato inválido (esperado YYYY-Wxx): $TARGET_WEEK" >> "$LOGFILE"
        exit 1
    fi
    YEAR="${TARGET_WEEK%-W*}"
    WEEK="${TARGET_WEEK#*-W}"
else
    # Default: semana ISO ANTERIOR. El viernes 18:00 corre con la
    # semana que ya cerró (lunes → domingo de la semana pasada).
    # La semana corriente está mid-week (Sat-Sun todavía no pasaron).
    # Truco: tomamos un día de hace 7 días — está garantizado que cae
    # en la semana ISO anterior — y leemos su año/semana ISO.
    REF_DATE=$(date -j -v-7d +%Y-%m-%d)
    YEAR=$(date -j -f %Y-%m-%d "$REF_DATE" +%G)
    WEEK=$(date -j -f %Y-%m-%d "$REF_DATE" +%V)
    TARGET_WEEK="${YEAR}-W${WEEK}"
fi

# Calcular fechas de inicio/fin de esa semana ISO (lunes → domingo).
# Truco: el jueves de una semana ISO siempre está en el año ISO de esa
# semana. Buscamos esa fecha vía un loop simple sobre el año.
WEEK_NUM_INT=$((10#$WEEK))
# Buscar el lunes de la semana ISO. Iteramos desde 1-ene del año ISO y
# encontramos el primer lunes (date -j ... +%V coincide con WEEK).
# Más simple: en macOS BSD date no hay -d "Mon Wn", así que usamos
# Python para esto (sigue sin deps externas).
WINDOW=$(python3 - "$YEAR" "$WEEK_NUM_INT" <<'PYEOF'
import sys
from datetime import date, timedelta
year = int(sys.argv[1])
week = int(sys.argv[2])
# ISO: lunes de la semana N del año ISO
# Truco: Jan 4 siempre está en la semana 1 ISO. El lunes de la semana 1
# es Jan 4 menos su weekday (Mon=0).
jan4 = date(year, 1, 4)
mon_w1 = jan4 - timedelta(days=jan4.weekday())
mon = mon_w1 + timedelta(weeks=week - 1)
sun = mon + timedelta(days=6)
print(f"{mon.isoformat()} {sun.isoformat()}")
PYEOF
)

WEEK_START=$(echo "$WINDOW" | awk '{print $1}')
WEEK_END=$(echo "$WINDOW" | awk '{print $2}')

echo "  TARGET_WEEK=$TARGET_WEEK  WINDOW=$WEEK_START → $WEEK_END" >> "$LOGFILE"

DIGEST_FILE="$VAULT_PATH/general/digests/${TARGET_WEEK}.md"

# ────────────────────────────────────
# Step 2: Invocar Claude
# ────────────────────────────────────
RUFINO_DISPLAY_NAME="${RUFINO_DISPLAY_NAME:-Val}"
RUFINO_DIGEST_DRY_RUN="${RUFINO_DIGEST_DRY_RUN:-0}"
EMAIL_HELPER="$HOME/.claude/scripts/rufino-send-email.py"

export RUFINO_VAULT_PATH RUFINO_DISPLAY_NAME
export RUFINO_DIGEST_TARGET_WEEK="$TARGET_WEEK"
export RUFINO_DIGEST_WEEK_START="$WEEK_START"
export RUFINO_DIGEST_WEEK_END="$WEEK_END"
export RUFINO_DIGEST_FILE="$DIGEST_FILE"
export RUFINO_DIGEST_DRY_RUN
export RUFINO_DIGEST_EMAIL_HELPER="$EMAIL_HELPER"
export RUFINO_DIGEST_EMAIL_TO="${RUFINO_DIGEST_EMAIL_TO:-valentinoerrandonea2002@gmail.com}"

PROMPT=$(envsubst '${RUFINO_VAULT_PATH} ${RUFINO_DISPLAY_NAME} ${RUFINO_DIGEST_TARGET_WEEK} ${RUFINO_DIGEST_WEEK_START} ${RUFINO_DIGEST_WEEK_END} ${RUFINO_DIGEST_FILE} ${RUFINO_DIGEST_DRY_RUN} ${RUFINO_DIGEST_EMAIL_HELPER} ${RUFINO_DIGEST_EMAIL_TO}' < "$PROMPT_FILE")

"$CLAUDE" -p "$PROMPT" \
    --allowedTools "Read,Write,Edit,Glob,Grep,Bash" \
    --dangerously-skip-permissions \
    --model sonnet \
    >> "$LOGFILE" 2>&1

echo "=== Rufino digest-weekly done: $(date) ===" >> "$LOGFILE"
