#!/bin/bash
# ─────────────────────────────────────────────────────────────
#  Rufino single-file processor
#  Usage: rufino-process-single.sh <vault-relative-path-or-absolute-path>
#
#  Invoked by the dashboard's server actions (spawn detached) whenever
#  the user saves/edits/imports a file. Runs Claude Code with the
#  rufino-process-single.md prompt and the target path substituted in.
# ─────────────────────────────────────────────────────────────
set -euo pipefail

if [ "$#" -lt 1 ]; then
    echo "Usage: $0 <target-file-path>"
    exit 1
fi

TARGET="$1"
LOGFILE="${RUFINO_LOG_DIR:-$HOME/.claude/logs/rufino}/rufino-process-single.log"
mkdir -p "$(dirname "$LOGFILE")"
PROMPT_FILE="$HOME/.claude/prompts/rufino-process-single.md"
CLAUDE="$(command -v claude || echo "$HOME/.local/bin/claude")"

# Resolve target to absolute path if relative
case "$TARGET" in
    /*) ABS_TARGET="$TARGET" ;;
    *)  ABS_TARGET="${RUFINO_VAULT_PATH:?RUFINO_VAULT_PATH must be set}/$TARGET" ;;
esac

if [ ! -f "$PROMPT_FILE" ]; then
    echo "ERROR: Prompt file not found at $PROMPT_FILE" >> "$LOGFILE"
    exit 1
fi

if [ ! -f "$ABS_TARGET" ]; then
    echo "=== $(date) | target gone, skipping: $ABS_TARGET ===" >> "$LOGFILE"
    exit 0
fi

echo "=== $(date) | processing: $ABS_TARGET ===" >> "$LOGFILE"

# Substitute the target path into the prompt
TARGET="$ABS_TARGET"
RUFINO_DISPLAY_NAME="${RUFINO_DISPLAY_NAME:-el usuario}"
export RUFINO_VAULT_PATH RUFINO_DISPLAY_NAME TARGET
PROMPT=$(envsubst '${RUFINO_VAULT_PATH} ${RUFINO_DISPLAY_NAME} ${TARGET}' < "$PROMPT_FILE")

"$CLAUDE" -p "$PROMPT" \
    --allowedTools "Read,Write,Edit,Glob,Grep,Bash" \
    --dangerously-skip-permissions \
    --model sonnet \
    >> "$LOGFILE" 2>&1

echo "=== $(date) | done: $ABS_TARGET ===" >> "$LOGFILE"
