#!/bin/bash
# ─────────────────────────────────────────────────────────────
#  Rufino import plan generator
#  Usage: rufino-import-plan.sh <inbox-file> <plan-json-file>
#
#  Invoked by the dashboard's submitImport server action (spawn detached)
#  whenever the user imports a doc. Runs Claude Code with the
#  rufino-import-plan.md prompt to upgrade the heuristic plan into a
#  high-quality LLM-driven plan.
# ─────────────────────────────────────────────────────────────
set -euo pipefail

if [ "$#" -lt 2 ]; then
    echo "Usage: $0 <inbox-file> <plan-json-file>"
    exit 1
fi

INBOX_FILE="$1"
PLAN_FILE="$2"
LOGFILE="${RUFINO_LOG_DIR:-$HOME/.claude/logs/rufino}/rufino-import-plan.log"
mkdir -p "$(dirname "$LOGFILE")"
PROMPT_FILE="$HOME/.claude/prompts/rufino-import-plan.md"
CLAUDE="$(command -v claude || echo "$HOME/.local/bin/claude")"

if [ ! -f "$PROMPT_FILE" ]; then
    echo "ERROR: Prompt file not found at $PROMPT_FILE" >> "$LOGFILE"
    exit 1
fi

if [ ! -f "$INBOX_FILE" ]; then
    echo "=== $(date) | inbox file gone, skipping: $INBOX_FILE ===" >> "$LOGFILE"
    exit 0
fi

if [ ! -f "$PLAN_FILE" ]; then
    echo "=== $(date) | plan file missing: $PLAN_FILE ===" >> "$LOGFILE"
    exit 1
fi

echo "=== $(date) | planning import: $INBOX_FILE → $PLAN_FILE ===" >> "$LOGFILE"

# Substitute the paths into the prompt
export INBOX_FILE PLAN_FILE
PROMPT=$(envsubst '${RUFINO_VAULT_PATH} ${RUFINO_DISPLAY_NAME} ${INBOX_FILE} ${PLAN_FILE}' < "$PROMPT_FILE")

"$CLAUDE" -p "$PROMPT" \
    --allowedTools "Read,Write,Glob,Grep,Bash" \
    --dangerously-skip-permissions \
    --model sonnet \
    >> "$LOGFILE" 2>&1

echo "=== $(date) | import plan done: $PLAN_FILE ===" >> "$LOGFILE"
