#!/bin/bash
# ─────────────────────────────────────────────────────────────
#  Rufino — Cross-source person resolver (Fase 4)
#
#  Thin wrapper sobre rufino-person-resolver.py. Es un script
#  on-demand — Val lo lanza manualmente. NO hay LaunchAgent.
#
#  Uso:
#    rufino-person-resolver.sh                  # genera questions
#    rufino-person-resolver.sh --dry-run        # solo reporta
#    rufino-person-resolver.sh --verbose        # muestra top pares
#
#  Variables de entorno:
#    RUFINO_VAULT_PATH    obligatorio.
# ─────────────────────────────────────────────────────────────

set -euo pipefail

: "${RUFINO_VAULT_PATH:?RUFINO_VAULT_PATH must be set}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY_SCRIPT="$SCRIPT_DIR/rufino-person-resolver.py"

if [ ! -f "$PY_SCRIPT" ]; then
    echo "[error] No encuentro $PY_SCRIPT" >&2
    exit 1
fi

LOG_DIR="${RUFINO_LOG_DIR:-$HOME/.claude/logs/rufino}"
mkdir -p "$LOG_DIR"
LOGFILE="$LOG_DIR/rufino-person-resolver.log"

{
    echo "=== rufino-person-resolver start: $(date) ==="
    /usr/bin/env python3 "$PY_SCRIPT" "$@"
    echo "=== rufino-person-resolver end: $(date) ==="
} | tee -a "$LOGFILE"
