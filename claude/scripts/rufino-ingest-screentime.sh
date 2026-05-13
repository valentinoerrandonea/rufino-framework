#!/bin/bash
# ─────────────────────────────────────────────────────────────
#  Rufino — Screen Time ingestor
#  Weekly (Sundays 04:00). Agrega tiempo de uso por app desde la
#  semana ISO anterior y escribe facts al vault:
#    ${RUFINO_VAULT_PATH}/screentime/facts/<slug>.md
#  Audit trail dumped at:
#    ${RUFINO_VAULT_PATH}/screentime/raw/<YYYY-WW>.json
#
#  Fuente: ~/Library/Application Support/Knowledge/knowledgeC.db
#  IMPORTANTE: Requiere Full Disk Access para /bin/bash (TCC).
#    Si falla: System Settings → Privacy & Security → Full Disk
#    Access → agregar /bin/bash, después reload el LaunchAgent.
#
#  Requires:
#    - sqlite3 (system default OK)
#    - jq
#    - $RUFINO_VAULT_PATH set
# ─────────────────────────────────────────────────────────────
set -euo pipefail

LOGFILE="${RUFINO_LOG_DIR:-$HOME/.claude/logs/rufino}/rufino-ingest-screentime.log"
mkdir -p "$(dirname "$LOGFILE")"
PROMPT_FILE="$HOME/.claude/prompts/rufino-ingest-screentime.md"
CLAUDE="$(command -v claude || echo "$HOME/.local/bin/claude")"
VAULT_PATH="${RUFINO_VAULT_PATH:?RUFINO_VAULT_PATH must be set}"
LOCKFILE="$VAULT_PATH/_meta/.ingest-screentime.lock"
KNOWLEDGE_DB="$HOME/Library/Application Support/Knowledge/knowledgeC.db"

mkdir -p "$VAULT_PATH/_meta" "$VAULT_PATH/screentime/facts" "$VAULT_PATH/screentime/raw"

# Stale-lock-aware locking
if [ -f "$LOCKFILE" ]; then
    LOCK_PID=$(cat "$LOCKFILE" 2>/dev/null || echo "")
    if [ -n "$LOCK_PID" ] && kill -0 "$LOCK_PID" 2>/dev/null; then
        echo "=== Rufino ingest-screentime skipped: already running (PID $LOCK_PID) at $(date) ===" >> "$LOGFILE"
        exit 0
    fi
    rm -f "$LOCKFILE"
fi
echo "$$" > "$LOCKFILE"
trap 'rm -f "$LOCKFILE"' EXIT

echo "=== Rufino ingest-screentime run: $(date) ===" >> "$LOGFILE"

# Sanity: sqlite3 + jq present
if ! command -v sqlite3 >/dev/null 2>&1; then
    echo "ERROR: sqlite3 not installed" >> "$LOGFILE"
    exit 1
fi
if ! command -v jq >/dev/null 2>&1; then
    echo "ERROR: jq not installed" >> "$LOGFILE"
    exit 1
fi
if [ ! -f "$PROMPT_FILE" ]; then
    echo "ERROR: Prompt file not found at $PROMPT_FILE" >> "$LOGFILE"
    exit 1
fi
if [ ! -f "$KNOWLEDGE_DB" ]; then
    echo "ERROR: knowledgeC.db not found at $KNOWLEDGE_DB" >> "$LOGFILE"
    exit 1
fi

# TCC probe: try a trivial read. If it fails, abort with a helpful message.
if ! sqlite3 "$KNOWLEDGE_DB" "SELECT 1 FROM ZOBJECT LIMIT 1;" >/dev/null 2>>"$LOGFILE"; then
    cat >> "$LOGFILE" <<EOF
ERROR: Cannot read $KNOWLEDGE_DB (TCC denied).
Fix: System Settings → Privacy & Security → Full Disk Access → add /bin/bash.
     Then unload/reload the LaunchAgent:
       launchctl unload ~/Library/LaunchAgents/com.user.rufino-ingest-screentime.plist
       launchctl load   ~/Library/LaunchAgents/com.user.rufino-ingest-screentime.plist
EOF
    exit 1
fi

# ────────────────────────────────────
# Step 1: Compute target ISO week
# ────────────────────────────────────
# Default: previous ISO week. Override via RUFINO_SCREENTIME_FORCE_WEEK=YYYY-WW.
if [ -n "${RUFINO_SCREENTIME_FORCE_WEEK:-}" ]; then
    TARGET_WEEK="$RUFINO_SCREENTIME_FORCE_WEEK"
else
    # date -v-7d gives "last week's same DOW". Then %G-W%V → ISO year-week.
    TARGET_WEEK="$(date -v-7d +%G-W%V)"
fi

# Parse YYYY-WW
ISO_YEAR="${TARGET_WEEK%-W*}"
ISO_WEEK="${TARGET_WEEK#*-W}"

# Compute Monday of ISO week (ISO weeks start Monday).
# macOS `date` doesn't natively grok ISO week input; do it with Python.
read -r WEEK_START WEEK_END < <(python3 -c "
import datetime
y = int('$ISO_YEAR'); w = int('$ISO_WEEK')
monday = datetime.date.fromisocalendar(y, w, 1)
sunday = monday + datetime.timedelta(days=6)
print(monday.isoformat(), sunday.isoformat())
")

# Convert to Mac absolute time (seconds since 2001-01-01 UTC).
# We treat the week boundaries as local midnight → Mac absolute time.
START_UNIX=$(date -j -f "%Y-%m-%d %H:%M:%S" "${WEEK_START} 00:00:00" +%s)
# End = Monday of next week, 00:00 local. = WEEK_END + 1 day
END_DAY=$(date -j -f "%Y-%m-%d" -v+1d "${WEEK_END}" +%Y-%m-%d)
END_UNIX=$(date -j -f "%Y-%m-%d %H:%M:%S" "${END_DAY} 00:00:00" +%s)
START_MAC=$((START_UNIX - 978307200))
END_MAC=$((END_UNIX - 978307200))

RAW_FILE="$VAULT_PATH/screentime/raw/${TARGET_WEEK}.json"

echo "  Week: $TARGET_WEEK ($WEEK_START → $WEEK_END)  Mac range: $START_MAC..$END_MAC" >> "$LOGFILE"

# ────────────────────────────────────
# Step 2: Query knowledgeC.db
# ────────────────────────────────────
# Top 50 apps by total seconds (/app/usage stream).
TMP_TSV="$(mktemp -t rufino-screentime-XXXXXX).tsv"
sqlite3 -separator $'\t' "$KNOWLEDGE_DB" <<SQL > "$TMP_TSV" 2>>"$LOGFILE"
SELECT
    COALESCE(ZVALUESTRING, '<unknown>') AS bundle_id,
    CAST(SUM(ZENDDATE - ZSTARTDATE) AS INTEGER) AS total_seconds,
    COUNT(*) AS sessions
FROM ZOBJECT
WHERE ZSTREAMNAME = '/app/usage'
  AND ZSTARTDATE >= $START_MAC
  AND ZENDDATE   <= $END_MAC
  AND ZENDDATE > ZSTARTDATE
GROUP BY ZVALUESTRING
ORDER BY total_seconds DESC
LIMIT 50;
SQL

# Total seconds across the week (all apps, including the long tail).
TOTAL_SECONDS=$(sqlite3 "$KNOWLEDGE_DB" "
SELECT COALESCE(CAST(SUM(ZENDDATE - ZSTARTDATE) AS INTEGER), 0)
FROM ZOBJECT
WHERE ZSTREAMNAME = '/app/usage'
  AND ZSTARTDATE >= $START_MAC
  AND ZENDDATE   <= $END_MAC
  AND ZENDDATE > ZSTARTDATE;
" 2>>"$LOGFILE")

# Build the JSON.
jq -Rn \
    --arg week "$TARGET_WEEK" \
    --arg week_start "$WEEK_START" \
    --arg week_end "$WEEK_END" \
    --argjson total_seconds "${TOTAL_SECONDS:-0}" \
    --rawfile tsv "$TMP_TSV" \
    '
    def parse_row:
        split("\t") as $p
        | { bundle_id: $p[0], total_seconds: ($p[1] | tonumber), sessions: ($p[2] | tonumber) };
    {
      week: $week,
      week_start: $week_start,
      week_end: $week_end,
      total_seconds: $total_seconds,
      top_apps: ($tsv | split("\n") | map(select(length > 0)) | map(parse_row))
    }
    ' > "$RAW_FILE"

rm -f "$TMP_TSV"

# Short-circuit: nothing to do if zero activity.
HAS_ACTIVITY=$(jq -r '(.total_seconds // 0) > 0' "$RAW_FILE")
if [ "$HAS_ACTIVITY" != "true" ]; then
    echo "  No Screen Time activity for $TARGET_WEEK. Skipping Claude invocation." >> "$LOGFILE"
    echo "=== Rufino ingest-screentime done (no-op): $(date) ===" >> "$LOGFILE"
    exit 0
fi

# ────────────────────────────────────
# Step 3: Invoke Claude with the prompt
# ────────────────────────────────────
RUFINO_DISPLAY_NAME="${RUFINO_DISPLAY_NAME:-el usuario}"
export RUFINO_VAULT_PATH RUFINO_DISPLAY_NAME
export RUFINO_SCREENTIME_RAW_FILE="$RAW_FILE"
export RUFINO_SCREENTIME_WEEK="$TARGET_WEEK"
export RUFINO_SCREENTIME_WEEK_START="$WEEK_START"
export RUFINO_SCREENTIME_WEEK_END="$WEEK_END"

PROMPT=$(envsubst '${RUFINO_VAULT_PATH} ${RUFINO_DISPLAY_NAME} ${RUFINO_SCREENTIME_RAW_FILE} ${RUFINO_SCREENTIME_WEEK} ${RUFINO_SCREENTIME_WEEK_START} ${RUFINO_SCREENTIME_WEEK_END}' < "$PROMPT_FILE")

"$CLAUDE" -p "$PROMPT" \
    --allowedTools "Read,Write,Edit,Glob,Grep,Bash" \
    --dangerously-skip-permissions \
    --model sonnet \
    >> "$LOGFILE" 2>&1

echo "=== Rufino ingest-screentime done: $(date) ===" >> "$LOGFILE"
