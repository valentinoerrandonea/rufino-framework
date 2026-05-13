#!/bin/bash
# ─────────────────────────────────────────────────────────────
#  Rufino — Apple Calendar ingestor
#  Daily 07:00. Reads events from yesterday in the local Apple
#  Calendar SQLite DB and writes facts to:
#    ${RUFINO_VAULT_PATH}/calendar/facts/<slug>.md
#  Audit trail dumped at:
#    ${RUFINO_VAULT_PATH}/calendar/raw/<YYYY-MM-DD>.json
#
#  Requires:
#    - macOS with Apple Calendar configured
#    - sqlite3 (system) + jq
#    - $RUFINO_VAULT_PATH set
#    - TCC: Full Disk Access for /bin/bash (or whatever binary the
#      LaunchAgent uses) so it can read
#      ~/Library/Group Containers/group.com.apple.calendar/Calendar.sqlitedb
# ─────────────────────────────────────────────────────────────
set -euo pipefail

LOGFILE="${RUFINO_LOG_DIR:-$HOME/.claude/logs/rufino}/rufino-ingest-calendar.log"
mkdir -p "$(dirname "$LOGFILE")"
PROMPT_FILE="$HOME/.claude/prompts/rufino-ingest-calendar.md"
CLAUDE="$(command -v claude || echo "$HOME/.local/bin/claude")"
VAULT_PATH="${RUFINO_VAULT_PATH:?RUFINO_VAULT_PATH must be set}"
LOCKFILE="$VAULT_PATH/_meta/.ingest-calendar.lock"

mkdir -p "$VAULT_PATH/_meta" "$VAULT_PATH/calendar/facts" "$VAULT_PATH/calendar/raw"

# Stale-lock-aware locking
if [ -f "$LOCKFILE" ]; then
    LOCK_PID=$(cat "$LOCKFILE" 2>/dev/null || echo "")
    if [ -n "$LOCK_PID" ] && kill -0 "$LOCK_PID" 2>/dev/null; then
        echo "=== Rufino ingest-calendar skipped: already running (PID $LOCK_PID) at $(date) ===" >> "$LOGFILE"
        exit 0
    fi
    rm -f "$LOCKFILE"
fi
echo "$$" > "$LOCKFILE"
trap 'rm -f "$LOCKFILE"' EXIT

echo "=== Rufino ingest-calendar run: $(date) ===" >> "$LOGFILE"

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

# ────────────────────────────────────
# Step 1: Locate the Calendar DB
# ────────────────────────────────────
CAL_DB_SRC="$HOME/Library/Group Containers/group.com.apple.calendar/Calendar.sqlitedb"

if [ ! -f "$CAL_DB_SRC" ]; then
    echo "ERROR: Calendar DB not found at $CAL_DB_SRC" >> "$LOGFILE"
    echo "Is Apple Calendar configured on this machine?" >> "$LOGFILE"
    exit 1
fi

# Try a trivial read to surface TCC denials cleanly. macOS may return
# "Operation not permitted" or "authorization denied" depending on the
# layer that's blocking access.
if ! sqlite3 "$CAL_DB_SRC" "SELECT 1;" >/dev/null 2>"$LOGFILE.tcc-check"; then
    TCC_ERR=$(cat "$LOGFILE.tcc-check" 2>/dev/null || echo "unknown")
    rm -f "$LOGFILE.tcc-check"
    {
        echo "ERROR: Cannot read $CAL_DB_SRC"
        echo "       Underlying error: $TCC_ERR"
        echo ""
        echo "This is almost certainly TCC (Transparency, Consent, Control) denying access."
        echo "Fix: System Settings → Privacy & Security → Full Disk Access → add /bin/bash"
        echo "     (or whatever binary the LaunchAgent uses to spawn this script)."
        echo "     After granting, run:"
        echo "       launchctl unload ~/Library/LaunchAgents/com.user.rufino-ingest-calendar.plist"
        echo "       launchctl load ~/Library/LaunchAgents/com.user.rufino-ingest-calendar.plist"
    } >> "$LOGFILE"
    exit 1
fi
rm -f "$LOGFILE.tcc-check"

# Copy DB to a tmp file before querying. The live DB has -wal/-shm side files
# and may be locked; copying avoids contention with Calendar.app.
TMP_DIR="$(mktemp -d -t rufino-calendar.XXXXXX)"
trap 'rm -rf "$TMP_DIR"; rm -f "$LOCKFILE"' EXIT
CAL_DB="$TMP_DIR/Calendar.sqlitedb"
cp "$CAL_DB_SRC" "$CAL_DB"
# Also copy WAL/SHM siblings if present, so the snapshot is consistent.
for sib in "$CAL_DB_SRC-wal" "$CAL_DB_SRC-shm"; do
    [ -f "$sib" ] && cp "$sib" "$TMP_DIR/$(basename "$sib")" || true
done

# ────────────────────────────────────
# Step 2: Compute target date and run query
# ────────────────────────────────────
TARGET_DATE="${RUFINO_CALENDAR_FORCE_DATE:-$(date -v-1d +%Y-%m-%d)}"
RAW_FILE="$VAULT_PATH/calendar/raw/${TARGET_DATE}.json"

echo "  Date: $TARGET_DATE" >> "$LOGFILE"
echo "  DB: $CAL_DB (copied from $CAL_DB_SRC)" >> "$LOGFILE"

# Mac absolute time = unix epoch - 978307200 (2001-01-01 UTC).
# Filter events whose START date (in local tz) matches the target date.
# JSON output is built by sqlite3 with json_object / json_group_array.
sqlite3 "$CAL_DB" <<SQL > "$RAW_FILE.events"
.mode list
.headers off
SELECT json_object(
    'date', '${TARGET_DATE}',
    'events', COALESCE((
        SELECT json_group_array(json_object(
            'uuid', ci.UUID,
            'rowid', ci.ROWID,
            'summary', ci.summary,
            'description', ci.description,
            'start_local', datetime(ci.start_date + 978307200, 'unixepoch', 'localtime'),
            'end_local',   datetime(ci.end_date   + 978307200, 'unixepoch', 'localtime'),
            'start_tz', ci.start_tz,
            'end_tz', ci.end_tz,
            'all_day', ci.all_day,
            'url', ci.url,
            'status', ci.status,
            'calendar', c.title,
            'calendar_type', c.type,
            'location', l.title,
            'location_address', l.address,
            'participants', COALESCE((
                SELECT json_group_array(json_object(
                    'email', p.email,
                    'is_self', p.is_self,
                    'role', p.role,
                    'status', p.status
                ))
                FROM Participant p
                WHERE p.owner_id = ci.ROWID
            ), json('[]'))
        ))
        FROM CalendarItem ci
        JOIN Calendar c ON c.ROWID = ci.calendar_id
        LEFT JOIN Location l ON l.ROWID = ci.location_id
        WHERE date(ci.start_date + 978307200, 'unixepoch', 'localtime') = '${TARGET_DATE}'
          AND ci.summary IS NOT NULL
          AND ci.entity_type = 2  -- 2 = event in this macOS version (other types: reminders, etc.)
        ORDER BY ci.start_date
    ), json('[]'))
);
SQL

# Validate and normalize JSON output via jq
if ! jq -e '.' "$RAW_FILE.events" >/dev/null 2>>"$LOGFILE"; then
    echo "ERROR: sqlite3 produced invalid JSON" >> "$LOGFILE"
    cat "$RAW_FILE.events" >> "$LOGFILE"
    exit 1
fi
jq '.' "$RAW_FILE.events" > "$RAW_FILE"
rm -f "$RAW_FILE.events"

EVENT_COUNT=$(jq -r '.events | length' "$RAW_FILE")
echo "  Events found: $EVENT_COUNT" >> "$LOGFILE"

# Short-circuit: no events → exit cleanly
if [ "$EVENT_COUNT" = "0" ]; then
    echo "  No Calendar events on $TARGET_DATE. Skipping Claude invocation." >> "$LOGFILE"
    echo "=== Rufino ingest-calendar done (no-op): $(date) ===" >> "$LOGFILE"
    exit 0
fi

# ────────────────────────────────────
# Step 3: Invoke Claude with the prompt
# ────────────────────────────────────
RUFINO_DISPLAY_NAME="${RUFINO_DISPLAY_NAME:-el usuario}"
export RUFINO_VAULT_PATH RUFINO_DISPLAY_NAME
export RUFINO_CALENDAR_RAW_FILE="$RAW_FILE"
export RUFINO_CALENDAR_DATE="$TARGET_DATE"

PROMPT=$(envsubst '${RUFINO_VAULT_PATH} ${RUFINO_DISPLAY_NAME} ${RUFINO_CALENDAR_RAW_FILE} ${RUFINO_CALENDAR_DATE}' < "$PROMPT_FILE")

"$CLAUDE" -p "$PROMPT" \
    --allowedTools "Read,Write,Edit,Glob,Grep,Bash" \
    --dangerously-skip-permissions \
    --model sonnet \
    >> "$LOGFILE" 2>&1

echo "=== Rufino ingest-calendar done: $(date) ===" >> "$LOGFILE"
