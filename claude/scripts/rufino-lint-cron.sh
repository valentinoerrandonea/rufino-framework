#!/bin/bash
# ─────────────────────────────────────────────────────────────
#  Rufino Lint cron wrapper
#  Runs the lint prompt with Claude Code, writes _meta/lint-<date>.json
# ─────────────────────────────────────────────────────────────
set -euo pipefail

LOGFILE="${RUFINO_LOG_DIR:-$HOME/.claude/logs/rufino}/rufino-lint.log"
mkdir -p "$(dirname "$LOGFILE")"
PROMPT_FILE="$HOME/.claude/prompts/rufino-lint.md"
CLAUDE="$(command -v claude || echo "$HOME/.local/bin/claude")"
VAULT_PATH="${RUFINO_VAULT_PATH:?RUFINO_VAULT_PATH must be set}"
LOCKFILE="$VAULT_PATH/_meta/.lint.lock"

mkdir -p "$VAULT_PATH/_meta"

# Stale-lock-aware locking (matches rufino-cron.sh pattern)
if [ -f "$LOCKFILE" ]; then
    LOCK_PID=$(cat "$LOCKFILE" 2>/dev/null || echo "")
    if [ -n "$LOCK_PID" ] && kill -0 "$LOCK_PID" 2>/dev/null; then
        echo "=== Rufino lint skipped: already running (PID $LOCK_PID) at $(date) ===" >> "$LOGFILE"
        exit 0
    fi
    rm -f "$LOCKFILE"
fi
echo "$$" > "$LOCKFILE"
trap 'rm -f "$LOCKFILE"' EXIT

echo "=== Rufino lint run: $(date) ===" >> "$LOGFILE"

if [ ! -f "$PROMPT_FILE" ]; then
    echo "ERROR: Prompt file not found at $PROMPT_FILE" >> "$LOGFILE"
    exit 1
fi

RUFINO_DISPLAY_NAME="${RUFINO_DISPLAY_NAME:-el usuario}"
export RUFINO_VAULT_PATH RUFINO_DISPLAY_NAME
PROMPT=$(envsubst '${RUFINO_VAULT_PATH} ${RUFINO_DISPLAY_NAME}' < "$PROMPT_FILE")

"$CLAUDE" -p "$PROMPT" \
    --allowedTools "Read,Write,Glob,Grep,Bash" \
    --dangerously-skip-permissions \
    --model sonnet \
    >> "$LOGFILE" 2>&1

echo "=== Rufino lint done: $(date) ===" >> "$LOGFILE"
