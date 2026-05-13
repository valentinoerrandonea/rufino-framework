#!/bin/bash
# ─────────────────────────────────────────────────────────────
#  Rufino — Spotify ingestor
#  Weekly (Sundays 04:30). Fetches recently-played tracks via
#  Spotify Web API (`/me/player/recently-played`, limit 50, last
#  ~24h). Acumulamos los responses semanales en
#    ${RUFINO_VAULT_PATH}/spotify/raw/<YYYY-WW>.json
#  (la API sólo guarda 50 tracks ~24h → si querés cobertura
#  full-week, tendrías que correr más seguido; con el cron
#  semanal capturás sólo el snapshot del sábado→domingo, que
#  ya es señal útil de hábito actual.)
#
#  Después invocamos Claude con el prompt para emitir facts
#  agregados al vault:
#    ${RUFINO_VAULT_PATH}/spotify/facts/<slug>.md
#
#  Requires:
#    - $RUFINO_VAULT_PATH set
#    - jq, curl
#    - Credenciales en Keychain:
#        rufino-spotify-client-id     (Account val)
#        rufino-spotify-client-secret (Account val)
#        rufino-spotify-refresh-token (Account val)
#      El refresh token se obtiene con setup-spotify-auth.sh
#      (one-time, interactive).
# ─────────────────────────────────────────────────────────────
set -euo pipefail

LOGFILE="${RUFINO_LOG_DIR:-$HOME/.claude/logs/rufino}/rufino-ingest-spotify.log"
mkdir -p "$(dirname "$LOGFILE")"
PROMPT_FILE="$HOME/.claude/prompts/rufino-ingest-spotify.md"
CLAUDE="$(command -v claude || echo "$HOME/.local/bin/claude")"
VAULT_PATH="${RUFINO_VAULT_PATH:?RUFINO_VAULT_PATH must be set}"
LOCKFILE="$VAULT_PATH/_meta/.ingest-spotify.lock"
STATE_FILE="$VAULT_PATH/spotify/.state"

mkdir -p "$VAULT_PATH/_meta" "$VAULT_PATH/spotify/facts" "$VAULT_PATH/spotify/raw"

# Stale-lock-aware locking
if [ -f "$LOCKFILE" ]; then
    LOCK_PID=$(cat "$LOCKFILE" 2>/dev/null || echo "")
    if [ -n "$LOCK_PID" ] && kill -0 "$LOCK_PID" 2>/dev/null; then
        echo "=== Rufino ingest-spotify skipped: already running (PID $LOCK_PID) at $(date) ===" >> "$LOGFILE"
        exit 0
    fi
    rm -f "$LOCKFILE"
fi
echo "$$" > "$LOCKFILE"
trap 'rm -f "$LOCKFILE"' EXIT

echo "=== Rufino ingest-spotify run: $(date) ===" >> "$LOGFILE"

# ─── Sanity ───
for bin in curl jq python3 security; do
    if ! command -v "$bin" >/dev/null 2>&1; then
        echo "ERROR: $bin no está instalado" >> "$LOGFILE"
        exit 1
    fi
done
if [ ! -f "$PROMPT_FILE" ]; then
    echo "ERROR: Prompt file not found at $PROMPT_FILE" >> "$LOGFILE"
    exit 1
fi

# ─── Credenciales ───
CLIENT_ID=$(security find-generic-password -s rufino-spotify-client-id -a val -w 2>/dev/null || true)
CLIENT_SECRET=$(security find-generic-password -s rufino-spotify-client-secret -a val -w 2>/dev/null || true)
REFRESH_TOKEN=$(security find-generic-password -s rufino-spotify-refresh-token -a val -w 2>/dev/null || true)

if [ -z "$CLIENT_ID" ] || [ -z "$CLIENT_SECRET" ]; then
    echo "ERROR: faltan rufino-spotify-client-id / rufino-spotify-client-secret en Keychain" >> "$LOGFILE"
    exit 1
fi
if [ -z "$REFRESH_TOKEN" ]; then
    echo "ERROR: falta rufino-spotify-refresh-token en Keychain. Corré setup-spotify-auth.sh primero." >> "$LOGFILE"
    exit 1
fi

# ────────────────────────────────────
# Step 1: Target ISO week (la semana ISO que acaba de cerrar)
# ────────────────────────────────────
# Default: previous ISO week. Override via RUFINO_SPOTIFY_FORCE_WEEK=YYYY-WW.
if [ -n "${RUFINO_SPOTIFY_FORCE_WEEK:-}" ]; then
    TARGET_WEEK="$RUFINO_SPOTIFY_FORCE_WEEK"
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

RAW_FILE="$VAULT_PATH/spotify/raw/${TARGET_WEEK}.json"

echo "  Week: $TARGET_WEEK ($WEEK_START → $WEEK_END)" >> "$LOGFILE"

# ────────────────────────────────────
# Step 2: Refresh → access_token
# ────────────────────────────────────
TOKEN_RESPONSE=$(curl -s -X POST "https://accounts.spotify.com/api/token" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -u "${CLIENT_ID}:${CLIENT_SECRET}" \
    --data-urlencode "grant_type=refresh_token" \
    --data-urlencode "refresh_token=$REFRESH_TOKEN")

ACCESS_TOKEN=$(echo "$TOKEN_RESPONSE" | jq -r '.access_token // empty')
TOKEN_ERR=$(echo "$TOKEN_RESPONSE" | jq -r '.error // empty')

if [ -z "$ACCESS_TOKEN" ]; then
    echo "ERROR: no obtuve access_token. error=$TOKEN_ERR resp=$TOKEN_RESPONSE" >> "$LOGFILE"
    exit 1
fi

# Spotify a veces rota el refresh_token. Si vino uno nuevo, persistilo.
NEW_REFRESH=$(echo "$TOKEN_RESPONSE" | jq -r '.refresh_token // empty')
if [ -n "$NEW_REFRESH" ] && [ "$NEW_REFRESH" != "$REFRESH_TOKEN" ]; then
    security delete-generic-password -s rufino-spotify-refresh-token -a val >/dev/null 2>&1 || true
    security add-generic-password -s rufino-spotify-refresh-token -a val -w "$NEW_REFRESH" >/dev/null 2>&1
    echo "  refresh_token rotated, persisted to Keychain" >> "$LOGFILE"
fi

# ────────────────────────────────────
# Step 3: Determinar `after` timestamp (ms)
# ────────────────────────────────────
# El endpoint sólo soporta `after` o `before` (uno). Usamos `after` con el
# played_at del último track de la corrida anterior, así no re-fetcheamos
# duplicados. Si no hay .state, default = hace 7 días.
if [ -f "$STATE_FILE" ]; then
    AFTER_MS=$(cat "$STATE_FILE" 2>/dev/null | tr -d '[:space:]')
fi
if ! [[ "${AFTER_MS:-}" =~ ^[0-9]+$ ]]; then
    # 7 días atrás en ms desde epoch
    AFTER_MS=$(python3 -c "import time; print(int((time.time() - 7*86400) * 1000))")
    echo "  No state file, defaulting after=$AFTER_MS (7d ago)" >> "$LOGFILE"
else
    echo "  after=$AFTER_MS (from .state)" >> "$LOGFILE"
fi

# ────────────────────────────────────
# Step 4: GET /me/player/recently-played
# ────────────────────────────────────
API_RESPONSE=$(curl -s -G \
    -H "Authorization: Bearer $ACCESS_TOKEN" \
    --data-urlencode "limit=50" \
    --data-urlencode "after=$AFTER_MS" \
    "https://api.spotify.com/v1/me/player/recently-played")

# Detectar errores HTTP en el JSON
API_ERR=$(echo "$API_RESPONSE" | jq -r '.error.message // empty')
if [ -n "$API_ERR" ]; then
    echo "ERROR: Spotify API: $API_ERR" >> "$LOGFILE"
    exit 1
fi

NEW_COUNT=$(echo "$API_RESPONSE" | jq -r '.items | length')
echo "  Fetched $NEW_COUNT new tracks" >> "$LOGFILE"

# ────────────────────────────────────
# Step 5: Merge con el raw acumulado de la semana
# ────────────────────────────────────
# Acumulamos por semana: si el archivo ya existe, hacemos merge dedup por
# played_at + track.id. Cada item se aplana a un schema compacto.

NEW_ITEMS=$(echo "$API_RESPONSE" | jq '[.items[] | {
    played_at: .played_at,
    track_id: .track.id,
    track_name: .track.name,
    artists: [.track.artists[].name],
    artist_ids: [.track.artists[].id],
    album_name: .track.album.name,
    album_id: .track.album.id,
    duration_ms: .track.duration_ms,
    explicit: .track.explicit,
    popularity: .track.popularity,
    uri: .track.uri
}]')

if [ -f "$RAW_FILE" ]; then
    EXISTING=$(jq '.items // []' "$RAW_FILE")
else
    EXISTING='[]'
fi

MERGED_ITEMS=$(jq -n \
    --argjson existing "$EXISTING" \
    --argjson new "$NEW_ITEMS" \
    '($existing + $new)
     | unique_by(.played_at + "|" + (.track_id // ""))
     | sort_by(.played_at)')

TOTAL_TRACKS=$(echo "$MERGED_ITEMS" | jq 'length')

# Compute the actual time range covered by data (puede ser > semana objetivo
# si está acumulando varias corridas)
FIRST_PLAYED=$(echo "$MERGED_ITEMS" | jq -r 'if length > 0 then .[0].played_at else null end')
LAST_PLAYED=$(echo "$MERGED_ITEMS" | jq -r 'if length > 0 then .[-1].played_at else null end')

jq -n \
    --arg week "$TARGET_WEEK" \
    --arg week_start "$WEEK_START" \
    --arg week_end "$WEEK_END" \
    --argjson total_tracks "$TOTAL_TRACKS" \
    --arg first_played "${FIRST_PLAYED:-}" \
    --arg last_played "${LAST_PLAYED:-}" \
    --argjson items "$MERGED_ITEMS" \
    '{
      week: $week,
      week_start: $week_start,
      week_end: $week_end,
      total_tracks: $total_tracks,
      first_played: (if $first_played == "" then null else $first_played end),
      last_played: (if $last_played == "" then null else $last_played end),
      items: $items
    }' > "$RAW_FILE"

# ────────────────────────────────────
# Step 6: Update .state con cursor del último played_at
# ────────────────────────────────────
# El response trae `cursors.after` (timestamp ms del más reciente), lo usamos
# como cursor para la próxima corrida. Si vino vacío y no hay tracks nuevos,
# dejamos el state como estaba.
NEXT_CURSOR=$(echo "$API_RESPONSE" | jq -r '.cursors.after // empty')
if [ -n "$NEXT_CURSOR" ] && [[ "$NEXT_CURSOR" =~ ^[0-9]+$ ]]; then
    echo "$NEXT_CURSOR" > "$STATE_FILE"
    echo "  .state updated → $NEXT_CURSOR" >> "$LOGFILE"
elif [ "$NEW_COUNT" -gt 0 ]; then
    # Fallback: convertir last played_at a ms si la API no devolvió cursor.
    LAST_MS=$(python3 -c "
import sys, datetime
ts = sys.argv[1]
# normalize: '2026-05-13T08:32:14.123Z' o sin millis
ts = ts.replace('Z', '+00:00')
print(int(datetime.datetime.fromisoformat(ts).timestamp() * 1000))
" "$LAST_PLAYED" 2>/dev/null || true)
    if [[ "$LAST_MS" =~ ^[0-9]+$ ]]; then
        echo "$LAST_MS" > "$STATE_FILE"
        echo "  .state updated → $LAST_MS (fallback from last_played)" >> "$LOGFILE"
    fi
fi

# ────────────────────────────────────
# Step 7: Short-circuit si no hay tracks (ni nuevos ni acumulados)
# ────────────────────────────────────
if [ "$TOTAL_TRACKS" -eq 0 ]; then
    echo "  No tracks for $TARGET_WEEK. Skipping Claude invocation." >> "$LOGFILE"
    echo "=== Rufino ingest-spotify done (no-op): $(date) ===" >> "$LOGFILE"
    exit 0
fi

# ────────────────────────────────────
# Step 8: Invoke Claude
# ────────────────────────────────────
RUFINO_DISPLAY_NAME="${RUFINO_DISPLAY_NAME:-el usuario}"
export RUFINO_VAULT_PATH RUFINO_DISPLAY_NAME
export RUFINO_SPOTIFY_RAW_FILE="$RAW_FILE"
export RUFINO_SPOTIFY_WEEK="$TARGET_WEEK"
export RUFINO_SPOTIFY_WEEK_START="$WEEK_START"
export RUFINO_SPOTIFY_WEEK_END="$WEEK_END"

PROMPT=$(envsubst '${RUFINO_VAULT_PATH} ${RUFINO_DISPLAY_NAME} ${RUFINO_SPOTIFY_RAW_FILE} ${RUFINO_SPOTIFY_WEEK} ${RUFINO_SPOTIFY_WEEK_START} ${RUFINO_SPOTIFY_WEEK_END}' < "$PROMPT_FILE")

"$CLAUDE" -p "$PROMPT" \
    --allowedTools "Read,Write,Edit,Glob,Grep,Bash" \
    --dangerously-skip-permissions \
    --model sonnet \
    >> "$LOGFILE" 2>&1

echo "=== Rufino ingest-spotify done: $(date) ===" >> "$LOGFILE"
