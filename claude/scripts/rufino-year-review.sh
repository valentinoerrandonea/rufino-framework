#!/bin/bash
# ─────────────────────────────────────────────────────────────
#  Rufino — Año en revisión (year in review)
#
#  Annual (30 dic @ 13:00 local). Genera una retrospectiva
#  narrativa del año recorriendo TODO el vault: facts externos,
#  decisiones, aprendizajes, sesiones, personas, pendientes
#  completados. El resultado es un documento largo tipo
#  "Spotify Wrapped textual".
#
#  Output:
#    ${RUFINO_VAULT_PATH}/general/year-in-review/<YYYY>.md
#
#  Override del año target (útil para correr "año hasta acá"
#  en cualquier momento, o regenerar un año pasado):
#    RUFINO_YEAR_FORCE=2026 bash ~/.claude/scripts/rufino-year-review.sh
#
#  Default: si estamos en diciembre, target = año actual.
#  Si NO estamos en diciembre, target = año actual también
#  (genera un "año hasta acá" parcial). El cron real corre
#  el 30 de diciembre así que el default funciona.
#
#  Dependencias: $RUFINO_VAULT_PATH set, claude CLI.
# ─────────────────────────────────────────────────────────────
set -euo pipefail

LOGFILE="${RUFINO_LOG_DIR:-$HOME/.claude/logs/rufino}/rufino-year-review.log"
mkdir -p "$(dirname "$LOGFILE")"
PROMPT_FILE="$HOME/.claude/prompts/rufino-year-review.md"
CLAUDE="$(command -v claude || echo "$HOME/.local/bin/claude")"
VAULT_PATH="${RUFINO_VAULT_PATH:?RUFINO_VAULT_PATH must be set}"
LOCKFILE="$VAULT_PATH/_meta/.year-review.lock"

mkdir -p "$VAULT_PATH/_meta" "$VAULT_PATH/general/year-in-review"

# Stale-lock-aware locking
if [ -f "$LOCKFILE" ]; then
    LOCK_PID=$(cat "$LOCKFILE" 2>/dev/null || echo "")
    if [ -n "$LOCK_PID" ] && kill -0 "$LOCK_PID" 2>/dev/null; then
        echo "=== Rufino year-review skipped: already running (PID $LOCK_PID) at $(date) ===" >> "$LOGFILE"
        exit 0
    fi
    rm -f "$LOCKFILE"
fi
echo "$$" > "$LOCKFILE"
trap 'rm -f "$LOCKFILE"' EXIT

echo "=== Rufino year-review run: $(date) ===" >> "$LOGFILE"

# ─── Sanity ───
if [ ! -f "$PROMPT_FILE" ]; then
    echo "ERROR: Prompt file not found at $PROMPT_FILE" >> "$LOGFILE"
    exit 1
fi
if [ ! -x "$CLAUDE" ] && ! command -v claude >/dev/null 2>&1; then
    echo "ERROR: claude CLI not found" >> "$LOGFILE"
    exit 1
fi

# ────────────────────────────────────
# Step 1: Determinar año target
# ────────────────────────────────────
# Override explícito gana. Default: año actual.
if [ -n "${RUFINO_YEAR_FORCE:-}" ]; then
    TARGET_YEAR="$RUFINO_YEAR_FORCE"
else
    TARGET_YEAR="$(date +%Y)"
fi

if ! [[ "$TARGET_YEAR" =~ ^[0-9]{4}$ ]]; then
    echo "ERROR: TARGET_YEAR invalid: $TARGET_YEAR" >> "$LOGFILE"
    exit 1
fi

YEAR_START="${TARGET_YEAR}-01-01"
YEAR_END="${TARGET_YEAR}-12-31"
OUTPUT_FILE="$VAULT_PATH/general/year-in-review/${TARGET_YEAR}.md"

echo "  Target year: $TARGET_YEAR ($YEAR_START → $YEAR_END)" >> "$LOGFILE"
echo "  Output:      $OUTPUT_FILE" >> "$LOGFILE"

# ────────────────────────────────────
# Step 2: Pre-cómputo de stats numéricos (livianos)
# ────────────────────────────────────
# Calculamos algunos counts directos del vault con find/grep, así
# Claude no tiene que enumerar archivo por archivo. Estos counts
# son aproximados (basados en first_seen / created del frontmatter
# o el path), no la verdad absoluta — Claude puede refinarlos.

# Helper: count files cuyo frontmatter tenga `first_seen: YYYY-...`
# o `created: YYYY-...` en el año target.
# Nota: `grep -r` exit 1 cuando no hay matches → con `set -o pipefail`
# eso voltearía el script. Usamos `|| true` para neutralizar.
count_year_files() {
    local dir="$1"
    if [ ! -d "$dir" ]; then echo 0; return; fi
    local out
    out=$(grep -rlE "^(first_seen|created):[[:space:]]*${TARGET_YEAR}-" "$dir" 2>/dev/null || true)
    if [ -z "$out" ]; then echo 0; return; fi
    echo "$out" | wc -l | tr -d ' '
}

STATS_FACTS_GITHUB=$(count_year_files "$VAULT_PATH/github/facts")
STATS_FACTS_CALENDAR=$(count_year_files "$VAULT_PATH/calendar/facts")
STATS_FACTS_SPOTIFY=$(count_year_files "$VAULT_PATH/spotify/facts")
STATS_FACTS_YOUTUBE=$(count_year_files "$VAULT_PATH/youtube/facts")
STATS_FACTS_WHATSAPP=$(count_year_files "$VAULT_PATH/whatsapp/facts")
STATS_FACTS_BROWSING=$(count_year_files "$VAULT_PATH/browsing/facts")
STATS_FACTS_SCREENTIME=$(count_year_files "$VAULT_PATH/screentime/facts")
STATS_FACTS_APPLEHEALTH=$(count_year_files "$VAULT_PATH/applehealth/facts")
STATS_FACTS_GDRIVE=$(count_year_files "$VAULT_PATH/gdrive/facts")

# Sesiones del año (por nombre de archivo `YYYY-MM-DD-tema.md`)
if [ -d "$VAULT_PATH/sesiones" ]; then
    STATS_SESIONES=$(find "$VAULT_PATH/sesiones" -maxdepth 2 -name "${TARGET_YEAR}-*.md" -type f 2>/dev/null | wc -l | tr -d ' ')
else
    STATS_SESIONES=0
fi

# Decisiones y aprendizajes del año (con frontmatter del año)
# `set +e` localmente — wc puede recibir 0 inputs cuando no hay matches.
STATS_DECISIONES=0
STATS_APRENDIZAJES=0
if [ -d "$VAULT_PATH/proyectos" ]; then
    set +e
    YEAR_NOTES=$(grep -rlE "^(created|first_seen):[[:space:]]*${TARGET_YEAR}-" "$VAULT_PATH/proyectos" 2>/dev/null || true)
    if [ -n "$YEAR_NOTES" ]; then
        STATS_DECISIONES=$(echo "$YEAR_NOTES" | xargs -n1 basename 2>/dev/null | grep -cE "^decision" || true)
        STATS_APRENDIZAJES=$(echo "$YEAR_NOTES" | xargs -n1 basename 2>/dev/null | grep -cE "^aprendizaje" || true)
    fi
    set -e
fi
STATS_DECISIONES=${STATS_DECISIONES:-0}
STATS_APRENDIZAJES=${STATS_APRENDIZAJES:-0}

# Personas registradas total (no por año — sirve como contexto)
if [ -d "$VAULT_PATH/rufino/_people" ]; then
    STATS_PERSONAS_TOTAL=$(find "$VAULT_PATH/rufino/_people" -maxdepth 1 -name "*.md" -type f 2>/dev/null | wc -l | tr -d ' ')
else
    STATS_PERSONAS_TOTAL=0
fi

{
    echo "  Pre-stats (${TARGET_YEAR}):"
    echo "    github facts:      $STATS_FACTS_GITHUB"
    echo "    calendar facts:    $STATS_FACTS_CALENDAR"
    echo "    spotify facts:     $STATS_FACTS_SPOTIFY"
    echo "    youtube facts:     $STATS_FACTS_YOUTUBE"
    echo "    whatsapp facts:    $STATS_FACTS_WHATSAPP"
    echo "    browsing facts:    $STATS_FACTS_BROWSING"
    echo "    screentime facts:  $STATS_FACTS_SCREENTIME"
    echo "    applehealth facts: $STATS_FACTS_APPLEHEALTH"
    echo "    gdrive facts:      $STATS_FACTS_GDRIVE"
    echo "    sesiones:          $STATS_SESIONES"
    echo "    decisiones:        $STATS_DECISIONES"
    echo "    aprendizajes:      $STATS_APRENDIZAJES"
    echo "    personas total:    $STATS_PERSONAS_TOTAL"
} >> "$LOGFILE"

# ────────────────────────────────────
# Step 3: Cobertura parcial detection
# ────────────────────────────────────
# Si la corrida es antes del 30 dic del año target, marcamos
# `coverage: partial`. El prompt lo refleja en el documento.
TODAY="$(date +%Y-%m-%d)"
CUTOFF="${TARGET_YEAR}-12-30"
if [ "$TODAY" \< "$CUTOFF" ]; then
    COVERAGE="partial"
    COVERAGE_NOTE="Año aún en curso al momento de la corrida (${TODAY}). Documento marca cobertura parcial."
else
    COVERAGE="full"
    COVERAGE_NOTE="Año completo cubierto."
fi
echo "  Coverage: $COVERAGE — $COVERAGE_NOTE" >> "$LOGFILE"

# ────────────────────────────────────
# Step 4: Invoke Claude
# ────────────────────────────────────
RUFINO_DISPLAY_NAME="${RUFINO_DISPLAY_NAME:-el usuario}"
export RUFINO_VAULT_PATH RUFINO_DISPLAY_NAME
export RUFINO_YEAR="$TARGET_YEAR"
export RUFINO_YEAR_START="$YEAR_START"
export RUFINO_YEAR_END="$YEAR_END"
export RUFINO_YEAR_OUTPUT_FILE="$OUTPUT_FILE"
export RUFINO_YEAR_COVERAGE="$COVERAGE"
export RUFINO_YEAR_TODAY="$TODAY"

# Stats (counts pre-computed). Claude puede refinarlos pero tener
# una base concreta evita inventos.
export RUFINO_STATS_FACTS_GITHUB="$STATS_FACTS_GITHUB"
export RUFINO_STATS_FACTS_CALENDAR="$STATS_FACTS_CALENDAR"
export RUFINO_STATS_FACTS_SPOTIFY="$STATS_FACTS_SPOTIFY"
export RUFINO_STATS_FACTS_YOUTUBE="$STATS_FACTS_YOUTUBE"
export RUFINO_STATS_FACTS_WHATSAPP="$STATS_FACTS_WHATSAPP"
export RUFINO_STATS_FACTS_BROWSING="$STATS_FACTS_BROWSING"
export RUFINO_STATS_FACTS_SCREENTIME="$STATS_FACTS_SCREENTIME"
export RUFINO_STATS_FACTS_APPLEHEALTH="$STATS_FACTS_APPLEHEALTH"
export RUFINO_STATS_FACTS_GDRIVE="$STATS_FACTS_GDRIVE"
export RUFINO_STATS_SESIONES="$STATS_SESIONES"
export RUFINO_STATS_DECISIONES="$STATS_DECISIONES"
export RUFINO_STATS_APRENDIZAJES="$STATS_APRENDIZAJES"
export RUFINO_STATS_PERSONAS_TOTAL="$STATS_PERSONAS_TOTAL"

VARS='${RUFINO_VAULT_PATH} ${RUFINO_DISPLAY_NAME} ${RUFINO_YEAR} ${RUFINO_YEAR_START} ${RUFINO_YEAR_END} ${RUFINO_YEAR_OUTPUT_FILE} ${RUFINO_YEAR_COVERAGE} ${RUFINO_YEAR_TODAY} ${RUFINO_STATS_FACTS_GITHUB} ${RUFINO_STATS_FACTS_CALENDAR} ${RUFINO_STATS_FACTS_SPOTIFY} ${RUFINO_STATS_FACTS_YOUTUBE} ${RUFINO_STATS_FACTS_WHATSAPP} ${RUFINO_STATS_FACTS_BROWSING} ${RUFINO_STATS_FACTS_SCREENTIME} ${RUFINO_STATS_FACTS_APPLEHEALTH} ${RUFINO_STATS_FACTS_GDRIVE} ${RUFINO_STATS_SESIONES} ${RUFINO_STATS_DECISIONES} ${RUFINO_STATS_APRENDIZAJES} ${RUFINO_STATS_PERSONAS_TOTAL}'

PROMPT=$(envsubst "$VARS" < "$PROMPT_FILE")

"$CLAUDE" -p "$PROMPT" \
    --allowedTools "Read,Write,Edit,Glob,Grep,Bash" \
    --dangerously-skip-permissions \
    --model sonnet \
    >> "$LOGFILE" 2>&1

echo "=== Rufino year-review done: $(date) ===" >> "$LOGFILE"
