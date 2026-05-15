#!/bin/bash
# ─────────────────────────────────────────────────────────────
#  Rufino — YouTube backfill desde un Takeout local
#
#  Procesa un `historial-de-reproducciones.json` descargado a mano
#  (en lugar de esperar al export bimestral via Drive). Divide el
#  JSON por bimestre y invoca el prompt de YouTube para cada uno.
#
#  Uso:
#    RUFINO_VAULT_PATH=/path/to/vault \
#    RUFINO_YOUTUBE_BACKFILL_FILE='/path/to/historial-de-reproducciones.json' \
#    RUFINO_YOUTUBE_BACKFILL_SINCE=2025-05-13 \
#    bash ~/.claude/scripts/rufino-ingest-youtube-backfill.sh
#
#  Default SINCE = 12 meses atrás de hoy.
# ─────────────────────────────────────────────────────────────
set -euo pipefail

LOGFILE="${RUFINO_LOG_DIR:-$HOME/.claude/logs/rufino}/rufino-ingest-youtube-backfill.log"
mkdir -p "$(dirname "$LOGFILE")"
PROMPT_FILE="$HOME/.claude/prompts/rufino-ingest-youtube.md"
CLAUDE="$(command -v claude || echo "$HOME/.local/bin/claude")"
VAULT_PATH="${RUFINO_VAULT_PATH:?RUFINO_VAULT_PATH must be set}"
INPUT_JSON="${RUFINO_YOUTUBE_BACKFILL_FILE:?RUFINO_YOUTUBE_BACKFILL_FILE must be set}"
SINCE="${RUFINO_YOUTUBE_BACKFILL_SINCE:-$(date -v-12m +%Y-%m-%d)}"

mkdir -p "$VAULT_PATH/youtube/raw" "$VAULT_PATH/youtube/facts"

echo "=== Rufino youtube-backfill: $(date) ===" >> "$LOGFILE"
echo "  Input: $INPUT_JSON" >> "$LOGFILE"
echo "  Since: $SINCE" >> "$LOGFILE"

# Sanity
[ -f "$INPUT_JSON" ] || { echo "ERROR: $INPUT_JSON no existe" >> "$LOGFILE"; exit 1; }
[ -f "$PROMPT_FILE" ] || { echo "ERROR: prompt no encontrado en $PROMPT_FILE" >> "$LOGFILE"; exit 1; }
for bin in jq python3; do command -v "$bin" >/dev/null 2>&1 || { echo "ERROR: $bin missing" >> "$LOGFILE"; exit 1; }; done

# ────────────────────────────────────
# Dividir el JSON por bimestre (Python)
# ────────────────────────────────────
TMP_DIR=$(mktemp -d -t rufino-yt-backfill-XXXXXX)
trap 'rm -rf "$TMP_DIR"' EXIT

python3 <<EOF
import json, os, datetime, sys

with open("$INPUT_JSON") as f:
    items = json.load(f)

since = datetime.date.fromisoformat("$SINCE")

# Agrupar items por bimestre (YYYY-W odd-week-pair). Usamos meses pares: 01-02, 03-04, 05-06, 07-08, 09-10, 11-12
buckets = {}
for item in items:
    try:
        t = datetime.datetime.fromisoformat(item["time"].replace("Z", "+00:00"))
        d = t.date()
    except Exception:
        continue
    if d < since:
        continue
    bimester_start_month = ((d.month - 1) // 2) * 2 + 1
    key = f"{d.year}-bi{bimester_start_month:02d}"
    buckets.setdefault(key, []).append(item)

# Imprimir lista de bimestres a procesar (ordenados ascendente)
keys = sorted(buckets.keys())
for k in keys:
    items_for_bi = buckets[k]
    dates = [datetime.datetime.fromisoformat(i["time"].replace("Z", "+00:00")).date() for i in items_for_bi if "time" in i]
    if not dates:
        continue
    out_path = os.path.join("$TMP_DIR", f"{k}.json")
    with open(out_path, "w") as f:
        json.dump(items_for_bi, f, ensure_ascii=False)
    # Print: key, count, min_date, max_date, out_path
    print(f"{k}\t{len(items_for_bi)}\t{min(dates).isoformat()}\t{max(dates).isoformat()}\t{out_path}")
EOF

# Capturar la lista de bimestres
BIMESTERS_FILE="$TMP_DIR/bimesters.tsv"
python3 <<EOF > "$BIMESTERS_FILE"
import json, os, datetime
with open("$INPUT_JSON") as f:
    items = json.load(f)
since = datetime.date.fromisoformat("$SINCE")
buckets = {}
for item in items:
    try:
        t = datetime.datetime.fromisoformat(item["time"].replace("Z", "+00:00"))
        d = t.date()
    except Exception:
        continue
    if d < since:
        continue
    bimester_start_month = ((d.month - 1) // 2) * 2 + 1
    key = f"{d.year}-bi{bimester_start_month:02d}"
    buckets.setdefault(key, []).append(item)
keys = sorted(buckets.keys())
for k in keys:
    items_for_bi = buckets[k]
    dates = [datetime.datetime.fromisoformat(i["time"].replace("Z", "+00:00")).date() for i in items_for_bi if "time" in i]
    if not dates:
        continue
    out_path = os.path.join("$TMP_DIR", f"{k}.json")
    with open(out_path, "w") as f:
        json.dump(items_for_bi, f, ensure_ascii=False)
    print(f"{k}\t{len(items_for_bi)}\t{min(dates).isoformat()}\t{max(dates).isoformat()}\t{out_path}")
EOF

echo "  Bimestres a procesar:" >> "$LOGFILE"
cat "$BIMESTERS_FILE" >> "$LOGFILE"
echo "" >> "$LOGFILE"

RUFINO_DISPLAY_NAME="${RUFINO_DISPLAY_NAME:-el usuario}"
export RUFINO_VAULT_PATH RUFINO_DISPLAY_NAME

TOTAL_BIMESTERS=$(wc -l < "$BIMESTERS_FILE" | tr -d ' ')
CURRENT=0

while IFS=$'\t' read -r KEY COUNT DATE_MIN DATE_MAX TMP_PATH; do
    CURRENT=$((CURRENT + 1))
    echo "  [$CURRENT/$TOTAL_BIMESTERS] Bimestre $KEY: $COUNT items ($DATE_MIN → $DATE_MAX)" >> "$LOGFILE"

    # Convertir key (2026-bi05) a YYYY-MM (mes inicial del bimestre)
    MONTH=$(echo "$KEY" | sed 's/-bi/-/')   # ej "2026-05"

    # Copiar JSON al raw del vault (acumulativo si ya existe — append items dedup)
    RAW_FILE="$VAULT_PATH/youtube/raw/${MONTH}.json"
    if [ -f "$RAW_FILE" ]; then
        # Merge dedup por (titleUrl + time)
        jq -s 'add | unique_by(.titleUrl + "|" + .time)' "$RAW_FILE" "$TMP_PATH" > "${RAW_FILE}.merge" \
            && mv "${RAW_FILE}.merge" "$RAW_FILE"
    else
        cp "$TMP_PATH" "$RAW_FILE"
    fi

    export RUFINO_YOUTUBE_RAW_FILE="$RAW_FILE"
    export RUFINO_YOUTUBE_EXPORT_MONTH="$MONTH"
    export RUFINO_YOUTUBE_DATE_MIN="$DATE_MIN"
    export RUFINO_YOUTUBE_DATE_MAX="$DATE_MAX"

    PROMPT=$(envsubst '${RUFINO_VAULT_PATH} ${RUFINO_DISPLAY_NAME} ${RUFINO_YOUTUBE_RAW_FILE} ${RUFINO_YOUTUBE_EXPORT_MONTH} ${RUFINO_YOUTUBE_DATE_MIN} ${RUFINO_YOUTUBE_DATE_MAX}' < "$PROMPT_FILE")

    echo "  → invocando Claude Code para bimestre $KEY..." >> "$LOGFILE"
    "$CLAUDE" -p "$PROMPT" \
        --allowedTools "Read,Write,Edit,Glob,Grep,Bash" \
        --dangerously-skip-permissions \
        --model sonnet \
        >> "$LOGFILE" 2>&1
    echo "  ✓ $KEY procesado" >> "$LOGFILE"

done < "$BIMESTERS_FILE"

echo "=== Rufino youtube-backfill done: $(date) ===" >> "$LOGFILE"
echo "Backfill listo. $TOTAL_BIMESTERS bimestres procesados."
echo "Ver facts en \$RUFINO_VAULT_PATH/youtube/facts/"
