#!/bin/bash
# ─────────────────────────────────────────────────────────────
#  Rufino — Chrome history ingestor
#  Weekly Sundays 03:30. Reads the local Chrome `Default` profile
#  history DB (cuenta personal), aggregates the previous ISO week's
#  browsing patterns, and writes facts to:
#    ${RUFINO_VAULT_PATH}/chrome/facts/<slug>.md
#  Audit trail dumped at:
#    ${RUFINO_VAULT_PATH}/chrome/raw/<YYYY-WW>.json
#
#  Requires:
#    - `sqlite3` and `jq` (pre-installed on macOS / Homebrew)
#    - $RUFINO_VAULT_PATH set
#    - Read access to ~/Library/Application Support/Google/Chrome/Default/History
#      (no TCC required — Chrome's DB is readable by the user).
#
#  Chrome locks the file when open: we copy it to /tmp before querying.
# ─────────────────────────────────────────────────────────────
set -euo pipefail

LOGFILE="${RUFINO_LOG_DIR:-$HOME/.claude/logs/rufino}/rufino-ingest-chrome.log"
mkdir -p "$(dirname "$LOGFILE")"
PROMPT_FILE="$HOME/.claude/prompts/rufino-ingest-chrome.md"
CLAUDE="$(command -v claude || echo "$HOME/.local/bin/claude")"
VAULT_PATH="${RUFINO_VAULT_PATH:?RUFINO_VAULT_PATH must be set}"
LOCKFILE="$VAULT_PATH/_meta/.ingest-chrome.lock"
CHROME_DB="$HOME/Library/Application Support/Google/Chrome/Default/History"

mkdir -p "$VAULT_PATH/_meta" "$VAULT_PATH/chrome/facts" "$VAULT_PATH/chrome/raw"

# Stale-lock-aware locking (same pattern que rufino-ingest-github)
if [ -f "$LOCKFILE" ]; then
    LOCK_PID=$(cat "$LOCKFILE" 2>/dev/null || echo "")
    if [ -n "$LOCK_PID" ] && kill -0 "$LOCK_PID" 2>/dev/null; then
        echo "=== Rufino ingest-chrome skipped: already running (PID $LOCK_PID) at $(date) ===" >> "$LOGFILE"
        exit 0
    fi
    rm -f "$LOCKFILE"
fi
echo "$$" > "$LOCKFILE"
trap 'rm -f "$LOCKFILE"' EXIT

echo "=== Rufino ingest-chrome run: $(date) ===" >> "$LOGFILE"

# ─── Sanity checks ───
if ! command -v sqlite3 >/dev/null 2>&1; then
    echo "ERROR: sqlite3 not installed" >> "$LOGFILE"
    exit 1
fi
if ! command -v jq >/dev/null 2>&1; then
    echo "ERROR: jq not installed" >> "$LOGFILE"
    exit 1
fi
if [ ! -f "$CHROME_DB" ]; then
    echo "ERROR: Chrome history DB not found at $CHROME_DB" >> "$LOGFILE"
    exit 1
fi
if [ ! -f "$PROMPT_FILE" ]; then
    echo "ERROR: Prompt file not found at $PROMPT_FILE" >> "$LOGFILE"
    exit 1
fi

# ────────────────────────────────────
# Step 1: Determine target ISO week (default: previous closed week)
# ────────────────────────────────────
# Override via env: RUFINO_CHROME_FORCE_WEEK=YYYY-WW
if [ -n "${RUFINO_CHROME_FORCE_WEEK:-}" ]; then
    WEEK="$RUFINO_CHROME_FORCE_WEEK"
    YEAR=${WEEK%%-W*}
    WEEKNUM=${WEEK##*-W}
    JAN4="$YEAR-01-04"
    JAN4_DOW=$(date -j -f "%Y-%m-%d" "$JAN4" +%u)
    W1_MON=$(date -j -v-$((JAN4_DOW - 1))d -f "%Y-%m-%d" "$JAN4" +%Y-%m-%d)
    DAYS=$(( (10#$WEEKNUM - 1) * 7 ))
    MONDAY=$(date -j -v+${DAYS}d -f "%Y-%m-%d" "$W1_MON" +%Y-%m-%d)
else
    # Previous week: take today - 7d, then find its Monday
    REF=$(date -v-7d +%Y-%m-%d)
    DOW=$(date -j -f "%Y-%m-%d" "$REF" +%u)
    MONDAY=$(date -j -v-$((DOW - 1))d -f "%Y-%m-%d" "$REF" +%Y-%m-%d)
    WEEK=$(date -j -f "%Y-%m-%d" "$MONDAY" +%G-W%V)
fi

SUNDAY=$(date -j -v+6d -f "%Y-%m-%d" "$MONDAY" +%Y-%m-%d)
RAW_FILE="$VAULT_PATH/chrome/raw/${WEEK}.json"

echo "  Week: $WEEK  ($MONDAY → $SUNDAY)" >> "$LOGFILE"

# ────────────────────────────────────
# Step 2: Copy Chrome DB (it's locked while Chrome is open)
# ────────────────────────────────────
TMP_DB="/tmp/chrome_history_${WEEK}.db"
trap 'rm -f "$LOCKFILE" "$TMP_DB" "$TMP_DB-shm" "$TMP_DB-wal"' EXIT

cp "$CHROME_DB" "$TMP_DB"
chmod 600 "$TMP_DB"

# Quick smoke test that sqlite3 can open it
if ! sqlite3 "$TMP_DB" "SELECT COUNT(*) FROM urls LIMIT 1;" >/dev/null 2>>"$LOGFILE"; then
    echo "ERROR: copied DB at $TMP_DB is not readable" >> "$LOGFILE"
    exit 1
fi

# ────────────────────────────────────
# Step 3: Convert week boundaries to WebKit microseconds since 1601-01-01 UTC
# ────────────────────────────────────
START_UNIX=$(date -j -u -f "%Y-%m-%d %H:%M:%S" "$MONDAY 00:00:00" +%s)
END_UNIX=$(date -j -u -f "%Y-%m-%d %H:%M:%S" "$SUNDAY 23:59:59" +%s)
START_WEBKIT=$(( (START_UNIX + 11644473600) * 1000000 ))
END_WEBKIT=$(( (END_UNIX + 11644473600) * 1000000 ))

# ────────────────────────────────────
# Step 4: Run queries → JSON
# ────────────────────────────────────
# Top 50 domains by visit count
DOMAINS_JSON=$(sqlite3 "$TMP_DB" <<SQL | jq -Rn '[inputs | split("|") | {domain: .[0], visits: (.[1] | tonumber)}]'
.mode list
.separator |
SELECT
  CASE
    WHEN u.url LIKE '%://%/%' THEN substr(u.url, instr(u.url, '://') + 3, instr(substr(u.url, instr(u.url, '://') + 3) || '/', '/') - 1)
    ELSE u.url
  END AS domain,
  COUNT(*) AS visits
FROM visits v JOIN urls u ON u.id = v.url
WHERE v.visit_time >= $START_WEBKIT AND v.visit_time <= $END_WEBKIT
GROUP BY domain
ORDER BY visits DESC
LIMIT 50;
SQL
)

# Repeated queries (≥3 hits). Note: actual column is `normalized_term`, not `lower_term`.
QUERIES_JSON=$(sqlite3 "$TMP_DB" <<SQL | jq -Rn '[inputs | split("\t") | {query: .[0], count: (.[1] | tonumber)}]'
.mode list
.separator \t
SELECT kst.normalized_term, COUNT(*) AS cnt
FROM keyword_search_terms kst
JOIN urls u ON u.id = kst.url_id
JOIN visits v ON v.url = u.id
WHERE v.visit_time >= $START_WEBKIT AND v.visit_time <= $END_WEBKIT
GROUP BY kst.normalized_term
HAVING cnt >= 3
ORDER BY cnt DESC
LIMIT 50;
SQL
)

# Title-rich URLs visited multiple times — útil para detectar research topics.
# (top 30 URLs por visitas, con title, fuera del top dominios para no inflar)
URLS_JSON=$(sqlite3 "$TMP_DB" <<SQL | jq -Rn '[inputs | split("") | {url: .[0], title: .[1], visits: (.[2] | tonumber)}]'
.mode list
.separator \x01
SELECT u.url, COALESCE(u.title, ''), COUNT(*) AS cnt
FROM visits v JOIN urls u ON u.id = v.url
WHERE v.visit_time >= $START_WEBKIT AND v.visit_time <= $END_WEBKIT
GROUP BY u.id
HAVING cnt >= 2
ORDER BY cnt DESC
LIMIT 30;
SQL
)

TOTAL_VISITS=$(sqlite3 "$TMP_DB" "SELECT COUNT(*) FROM visits WHERE visit_time >= $START_WEBKIT AND visit_time <= $END_WEBKIT;")
DISTINCT_DOMAINS=$(echo "$DOMAINS_JSON" | jq 'length')

# Combine into single JSON for the prompt
jq -n \
    --arg week "$WEEK" \
    --arg monday "$MONDAY" \
    --arg sunday "$SUNDAY" \
    --argjson total_visits "$TOTAL_VISITS" \
    --argjson distinct_domains "$DISTINCT_DOMAINS" \
    --argjson domains "$DOMAINS_JSON" \
    --argjson queries "$QUERIES_JSON" \
    --argjson urls "$URLS_JSON" \
    '{
      week: $week,
      monday: $monday,
      sunday: $sunday,
      total_visits: $total_visits,
      distinct_domains: $distinct_domains,
      top_domains: $domains,
      repeated_queries: $queries,
      repeated_urls: $urls
    }' > "$RAW_FILE"

# ────────────────────────────────────
# Step 5: Cleanup tmp DB before invoking Claude
# ────────────────────────────────────
rm -f "$TMP_DB" "$TMP_DB-shm" "$TMP_DB-wal"
# Reset trap to only clean lockfile from here on
trap 'rm -f "$LOCKFILE"' EXIT

# Short-circuit if no activity (Chrome closed all week, fresh profile, etc.)
HAS_ACTIVITY=$(jq -r '(.total_visits // 0) > 0' "$RAW_FILE")
if [ "$HAS_ACTIVITY" != "true" ]; then
    echo "  No Chrome activity in $WEEK. Skipping Claude invocation." >> "$LOGFILE"
    echo "=== Rufino ingest-chrome done (no-op): $(date) ===" >> "$LOGFILE"
    exit 0
fi

echo "  total_visits=$TOTAL_VISITS distinct_domains=$DISTINCT_DOMAINS" >> "$LOGFILE"

# ────────────────────────────────────
# Step 6: Invoke Claude
# ────────────────────────────────────
RUFINO_DISPLAY_NAME="${RUFINO_DISPLAY_NAME:-el usuario}"
export RUFINO_VAULT_PATH RUFINO_DISPLAY_NAME
export RUFINO_CHROME_RAW_FILE="$RAW_FILE"
export RUFINO_CHROME_WEEK="$WEEK"
export RUFINO_CHROME_MONDAY="$MONDAY"
export RUFINO_CHROME_SUNDAY="$SUNDAY"

PROMPT=$(envsubst '${RUFINO_VAULT_PATH} ${RUFINO_DISPLAY_NAME} ${RUFINO_CHROME_RAW_FILE} ${RUFINO_CHROME_WEEK} ${RUFINO_CHROME_MONDAY} ${RUFINO_CHROME_SUNDAY}' < "$PROMPT_FILE")

"$CLAUDE" -p "$PROMPT" \
    --allowedTools "Read,Write,Edit,Glob,Grep,Bash" \
    --dangerously-skip-permissions \
    --model sonnet \
    >> "$LOGFILE" 2>&1

echo "=== Rufino ingest-chrome done: $(date) ===" >> "$LOGFILE"
