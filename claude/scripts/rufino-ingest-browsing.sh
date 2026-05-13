#!/bin/bash
# ─────────────────────────────────────────────────────────────
#  Rufino — Browsing history ingestor (Zen + Safari unificados)
#  Weekly (Sunday 03:30). Lee SQLite history de Zen y Safari
#  para la semana ISO anterior, dumpea raw JSON unificado y
#  delega procesamiento a Claude.
#
#  Fuentes:
#    - Zen (Firefox schema): ~/Library/Application Support/zen/Profiles/<profile>/places.sqlite
#    - Safari: ~/Library/Safari/History.db
#
#  Lockeo: ambos los browsers lockean la DB cuando están abiertos.
#  Solución: cp a /tmp/ antes de queries, cleanup al final.
#
#  Requires:
#    - sqlite3, jq, python3
#    - $RUFINO_VAULT_PATH set
# ─────────────────────────────────────────────────────────────
set -euo pipefail

LOGFILE="${RUFINO_LOG_DIR:-$HOME/.claude/logs/rufino}/rufino-ingest-browsing.log"
mkdir -p "$(dirname "$LOGFILE")"
PROMPT_FILE="$HOME/.claude/prompts/rufino-ingest-browsing.md"
CLAUDE="$(command -v claude || echo "$HOME/.local/bin/claude")"
VAULT_PATH="${RUFINO_VAULT_PATH:?RUFINO_VAULT_PATH must be set}"
LOCKFILE="$VAULT_PATH/_meta/.ingest-browsing.lock"

mkdir -p "$VAULT_PATH/_meta" "$VAULT_PATH/browsing/facts" "$VAULT_PATH/browsing/raw"

if [ -f "$LOCKFILE" ]; then
    LOCK_PID=$(cat "$LOCKFILE" 2>/dev/null || echo "")
    if [ -n "$LOCK_PID" ] && kill -0 "$LOCK_PID" 2>/dev/null; then
        echo "=== Rufino ingest-browsing skipped: already running (PID $LOCK_PID) at $(date) ===" >> "$LOGFILE"
        exit 0
    fi
    rm -f "$LOCKFILE"
fi
echo "$$" > "$LOCKFILE"

# Cleanup tmp DBs en EXIT (incluye errors)
TMP_DIR=$(mktemp -d -t rufino-browsing-XXXXXX)
trap 'rm -rf "$TMP_DIR" "$LOCKFILE"' EXIT

echo "=== Rufino ingest-browsing run: $(date) ===" >> "$LOGFILE"

# ────────────────────────────────────
# Semana ISO target (default: semana anterior, override via env)
# ────────────────────────────────────
TARGET_WEEK="${RUFINO_BROWSING_FORCE_WEEK:-$(python3 -c "
import datetime
today = datetime.date.today()
prev_week = today - datetime.timedelta(days=7)
y, w, _ = prev_week.isocalendar()
print(f'{y}-W{w:02d}')
")}"

# Calcular start/end de la semana ISO (Lunes/Domingo en local time)
WEEK_BOUNDS=$(python3 -c "
import datetime, sys
yyyy_ww = '$TARGET_WEEK'
y = int(yyyy_ww[:4])
w = int(yyyy_ww[6:])
start = datetime.date.fromisocalendar(y, w, 1)
end = datetime.date.fromisocalendar(y, w, 7)
print(f'{start.isoformat()} {end.isoformat()}')
")
WEEK_START=$(echo "$WEEK_BOUNDS" | awk '{print $1}')
WEEK_END=$(echo "$WEEK_BOUNDS" | awk '{print $2}')

# Unix timestamps de los bounds (start of Monday 00:00, end of Sunday 23:59:59)
UNIX_START=$(date -j -f "%Y-%m-%d %H:%M:%S" "${WEEK_START} 00:00:00" "+%s")
UNIX_END=$(date -j -f "%Y-%m-%d %H:%M:%S" "${WEEK_END} 23:59:59" "+%s")

# Zen (Firefox): microseconds since Unix epoch
ZEN_START=$((UNIX_START * 1000000))
ZEN_END=$((UNIX_END * 1000000))

# Safari: CFAbsoluteTime = seconds since 2001-01-01 UTC = unix - 978307200
SAFARI_EPOCH_OFFSET=978307200
SAFARI_START=$((UNIX_START - SAFARI_EPOCH_OFFSET))
SAFARI_END=$((UNIX_END - SAFARI_EPOCH_OFFSET))

echo "  Week: $TARGET_WEEK ($WEEK_START → $WEEK_END)" >> "$LOGFILE"
echo "  Unix: $UNIX_START → $UNIX_END" >> "$LOGFILE"

# ────────────────────────────────────
# Locate Zen profile + Safari DB
# ────────────────────────────────────
ZEN_SRC=$(find "$HOME/Library/Application Support/zen/Profiles" -maxdepth 2 -name "places.sqlite" 2>/dev/null | head -1)
SAFARI_SRC="$HOME/Library/Safari/History.db"

ZEN_TMP="$TMP_DIR/zen.sqlite"
SAFARI_TMP="$TMP_DIR/safari.sqlite"

# Privacy blacklist — dominios filtrados del fact body (mantenidos en raw)
PRIVACY_BLACKLIST='pornhub|xvideos|xnxx|redtube|mail\.google\.com|web\.whatsapp\.com|messages\.google\.com|tinder|bumble|grindr|doubleclick\.net|googletagmanager|googlesyndication'

# ────────────────────────────────────
# Zen — copy y query (si existe)
# ────────────────────────────────────
ZEN_RESULTS='{"top_domains":[],"queries_repeated":[],"top_urls":[],"total_visits":0,"profile":""}'
if [ -n "$ZEN_SRC" ] && [ -f "$ZEN_SRC" ]; then
    cp "$ZEN_SRC" "$ZEN_TMP" 2>>"$LOGFILE" || { echo "WARN: cp zen falló" >> "$LOGFILE"; }
    cp "${ZEN_SRC}-wal" "${ZEN_TMP}-wal" 2>/dev/null || true
    cp "${ZEN_SRC}-shm" "${ZEN_TMP}-shm" 2>/dev/null || true

    if [ -f "$ZEN_TMP" ]; then
        # Top domains
        ZEN_DOMAINS=$(sqlite3 "$ZEN_TMP" -separator $'\t' "
            SELECT
                CASE
                    WHEN p.url LIKE '%://%/%' THEN
                        substr(p.url, instr(p.url, '://')+3,
                               instr(substr(p.url, instr(p.url, '://')+3) || '/', '/')-1)
                    ELSE p.url
                END AS host,
                COUNT(*) AS visits
            FROM moz_historyvisits v JOIN moz_places p ON p.id = v.place_id
            WHERE v.visit_date >= $ZEN_START AND v.visit_date <= $ZEN_END
            GROUP BY host
            ORDER BY visits DESC
            LIMIT 50;
        " 2>>"$LOGFILE" | python3 -c "
import sys, json
rows = []
for line in sys.stdin:
    parts = line.rstrip('\n').split('\t')
    if len(parts) == 2 and parts[0]:
        rows.append({'host': parts[0], 'visits': int(parts[1])})
print(json.dumps(rows))
")

        # Top URLs (para identificar research clusters)
        ZEN_URLS=$(sqlite3 "$ZEN_TMP" -separator $'\x01' "
            SELECT p.url, p.title, COUNT(*) AS visits
            FROM moz_historyvisits v JOIN moz_places p ON p.id = v.place_id
            WHERE v.visit_date >= $ZEN_START AND v.visit_date <= $ZEN_END
            GROUP BY p.url
            ORDER BY visits DESC
            LIMIT 200;
        " 2>>"$LOGFILE" | python3 -c "
import sys, json
rows = []
for line in sys.stdin:
    parts = line.rstrip('\n').split('\x01')
    if len(parts) == 3 and parts[0]:
        rows.append({'url': parts[0], 'title': parts[1], 'visits': int(parts[2])})
print(json.dumps(rows))
")

        # Queries (Google search URLs): parsear ?q= en URLs de google.com/search
        ZEN_QUERIES=$(sqlite3 "$ZEN_TMP" "
            SELECT p.url
            FROM moz_historyvisits v JOIN moz_places p ON p.id = v.place_id
            WHERE v.visit_date >= $ZEN_START AND v.visit_date <= $ZEN_END
              AND p.url LIKE '%google.%/search?%q=%';
        " 2>>"$LOGFILE" | python3 -c "
import sys, json, urllib.parse, collections
counter = collections.Counter()
for url in sys.stdin:
    url = url.strip()
    try:
        qs = urllib.parse.urlparse(url).query
        params = urllib.parse.parse_qs(qs)
        q = params.get('q', [None])[0]
        if q:
            counter[q.lower()] += 1
    except Exception:
        continue
rows = [{'query': q, 'count': c} for q, c in counter.most_common() if c >= 3]
print(json.dumps(rows[:30]))
")

        ZEN_TOTAL=$(sqlite3 "$ZEN_TMP" "
            SELECT COUNT(*) FROM moz_historyvisits
            WHERE visit_date >= $ZEN_START AND visit_date <= $ZEN_END;
        " 2>>"$LOGFILE")

        ZEN_PROFILE=$(basename "$(dirname "$ZEN_SRC")")

        ZEN_RESULTS=$(jq -n \
            --argjson domains "${ZEN_DOMAINS:-[]}" \
            --argjson urls "${ZEN_URLS:-[]}" \
            --argjson queries "${ZEN_QUERIES:-[]}" \
            --argjson total "${ZEN_TOTAL:-0}" \
            --arg profile "$ZEN_PROFILE" \
            '{top_domains: $domains, top_urls: $urls, queries_repeated: $queries, total_visits: $total, profile: $profile}')
    fi
fi

# ────────────────────────────────────
# Safari — copy y query
# ────────────────────────────────────
SAFARI_RESULTS='{"top_domains":[],"queries_repeated":[],"top_urls":[],"total_visits":0}'
if [ -f "$SAFARI_SRC" ]; then
    cp "$SAFARI_SRC" "$SAFARI_TMP" 2>>"$LOGFILE" || { echo "WARN: cp safari falló" >> "$LOGFILE"; }
    cp "${SAFARI_SRC}-wal" "${SAFARI_TMP}-wal" 2>/dev/null || true
    cp "${SAFARI_SRC}-shm" "${SAFARI_TMP}-shm" 2>/dev/null || true

    if [ -f "$SAFARI_TMP" ]; then
        SAFARI_DOMAINS=$(sqlite3 "$SAFARI_TMP" -separator $'\t' "
            SELECT
                CASE
                    WHEN hi.url LIKE '%://%/%' THEN
                        substr(hi.url, instr(hi.url, '://')+3,
                               instr(substr(hi.url, instr(hi.url, '://')+3) || '/', '/')-1)
                    ELSE hi.url
                END AS host,
                COUNT(*) AS visits
            FROM history_visits hv JOIN history_items hi ON hi.id = hv.history_item
            WHERE hv.visit_time >= $SAFARI_START AND hv.visit_time <= $SAFARI_END
            GROUP BY host
            ORDER BY visits DESC
            LIMIT 50;
        " 2>>"$LOGFILE" | python3 -c "
import sys, json
rows = []
for line in sys.stdin:
    parts = line.rstrip('\n').split('\t')
    if len(parts) == 2 and parts[0]:
        rows.append({'host': parts[0], 'visits': int(parts[1])})
print(json.dumps(rows))
")

        SAFARI_URLS=$(sqlite3 "$SAFARI_TMP" -separator $'\x01' "
            SELECT hi.url, COALESCE(hv.title, '') AS title, COUNT(*) AS visits
            FROM history_visits hv JOIN history_items hi ON hi.id = hv.history_item
            WHERE hv.visit_time >= $SAFARI_START AND hv.visit_time <= $SAFARI_END
            GROUP BY hi.url
            ORDER BY visits DESC
            LIMIT 200;
        " 2>>"$LOGFILE" | python3 -c "
import sys, json
rows = []
for line in sys.stdin:
    parts = line.rstrip('\n').split('\x01')
    if len(parts) == 3 and parts[0]:
        rows.append({'url': parts[0], 'title': parts[1], 'visits': int(parts[2])})
print(json.dumps(rows))
")

        SAFARI_QUERIES=$(sqlite3 "$SAFARI_TMP" "
            SELECT hi.url
            FROM history_visits hv JOIN history_items hi ON hi.id = hv.history_item
            WHERE hv.visit_time >= $SAFARI_START AND hv.visit_time <= $SAFARI_END
              AND hi.url LIKE '%google.%/search?%q=%';
        " 2>>"$LOGFILE" | python3 -c "
import sys, json, urllib.parse, collections
counter = collections.Counter()
for url in sys.stdin:
    url = url.strip()
    try:
        qs = urllib.parse.urlparse(url).query
        params = urllib.parse.parse_qs(qs)
        q = params.get('q', [None])[0]
        if q:
            counter[q.lower()] += 1
    except Exception:
        continue
rows = [{'query': q, 'count': c} for q, c in counter.most_common() if c >= 3]
print(json.dumps(rows[:30]))
")

        SAFARI_TOTAL=$(sqlite3 "$SAFARI_TMP" "
            SELECT COUNT(*) FROM history_visits
            WHERE visit_time >= $SAFARI_START AND visit_time <= $SAFARI_END;
        " 2>>"$LOGFILE")

        SAFARI_RESULTS=$(jq -n \
            --argjson domains "${SAFARI_DOMAINS:-[]}" \
            --argjson urls "${SAFARI_URLS:-[]}" \
            --argjson queries "${SAFARI_QUERIES:-[]}" \
            --argjson total "${SAFARI_TOTAL:-0}" \
            '{top_domains: $domains, top_urls: $urls, queries_repeated: $queries, total_visits: $total}')
    fi
fi

# ────────────────────────────────────
# Unificar: sumar visits por host/url/query a través de los 2 browsers
# ────────────────────────────────────
UNIFIED=$(jq -n \
    --argjson zen "$ZEN_RESULTS" \
    --argjson safari "$SAFARI_RESULTS" \
    --arg week "$TARGET_WEEK" \
    --arg blacklist "$PRIVACY_BLACKLIST" \
    '{
        week: $week,
        zen: $zen,
        safari: $safari,
        privacy_blacklist_regex: $blacklist,
        merged: {
            top_domains: (
                ($zen.top_domains + $safari.top_domains)
                | group_by(.host)
                | map({host: .[0].host, visits: (map(.visits) | add)})
                | sort_by(-.visits)
                | .[0:30]
            ),
            queries_repeated: (
                ($zen.queries_repeated + $safari.queries_repeated)
                | group_by(.query)
                | map({query: .[0].query, count: (map(.count) | add)})
                | sort_by(-.count)
                | .[0:20]
            ),
            top_urls: (
                ($zen.top_urls + $safari.top_urls)
                | group_by(.url)
                | map({url: .[0].url, title: (map(.title) | map(select(. != "")) | first // ""), visits: (map(.visits) | add)})
                | sort_by(-.visits)
                | .[0:50]
            ),
            total_visits: ($zen.total_visits + $safari.total_visits)
        }
    }')

RAW_FILE="$VAULT_PATH/browsing/raw/${TARGET_WEEK}.json"
echo "$UNIFIED" > "$RAW_FILE"

TOTAL_VISITS=$(echo "$UNIFIED" | jq -r '.merged.total_visits')
echo "  Total visits: $TOTAL_VISITS" >> "$LOGFILE"

if [ "$TOTAL_VISITS" -eq 0 ]; then
    echo "  No browsing activity for $TARGET_WEEK. Skipping Claude invocation." >> "$LOGFILE"
    echo "=== done (no-op): $(date) ===" >> "$LOGFILE"
    exit 0
fi

# ────────────────────────────────────
# Invocar Claude
# ────────────────────────────────────
RUFINO_DISPLAY_NAME="${RUFINO_DISPLAY_NAME:-el usuario}"
export RUFINO_VAULT_PATH RUFINO_DISPLAY_NAME
export RUFINO_BROWSING_RAW_FILE="$RAW_FILE"
export RUFINO_BROWSING_WEEK="$TARGET_WEEK"
export RUFINO_BROWSING_WEEK_START="$WEEK_START"
export RUFINO_BROWSING_WEEK_END="$WEEK_END"

PROMPT=$(envsubst '${RUFINO_VAULT_PATH} ${RUFINO_DISPLAY_NAME} ${RUFINO_BROWSING_RAW_FILE} ${RUFINO_BROWSING_WEEK} ${RUFINO_BROWSING_WEEK_START} ${RUFINO_BROWSING_WEEK_END}' < "$PROMPT_FILE")

"$CLAUDE" -p "$PROMPT" \
    --allowedTools "Read,Write,Edit,Glob,Grep,Bash" \
    --dangerously-skip-permissions \
    --model sonnet \
    >> "$LOGFILE" 2>&1

echo "=== Rufino ingest-browsing done: $(date) ===" >> "$LOGFILE"
