#!/bin/bash
set -euo pipefail

# Read hook input from stdin (Claude Code passes JSON with session info)
HOOK_INPUT=$(cat)
SESSION_ID=$(echo "$HOOK_INPUT" | jq -r '.session_id')
FLAG="/tmp/claude-memory-check-${SESSION_ID}"

# If we've already been reminded this session, allow the stop
if [ -f "$FLAG" ]; then
    rm -f "$FLAG"
    exit 0
fi

# First time: remind and block
touch "$FLAG"
echo "OBSIDIAN MEMORY CHECK: revisá si hay algo para guardar en el vault antes de cerrar." >&2
exit 2
