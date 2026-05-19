#!/usr/bin/env bash
# Migration 0.0.2 → 0.0.3
#
# v0.0.3 renamed Memory loop hook + command artifacts to embed a per-vault
# slug. A v0.0.2 install would have left un-slugged files at:
#
#   ~/.claude/hooks/rufino-memory-loop-init.sh
#   ~/.claude/hooks/rufino-memory-loop-stop.sh
#   ~/.claude/commands/remember.md
#
# After upgrading, these are orphans (no longer referenced or installed by
# rufino) but otherwise harmless. We move them aside into the upgrade
# backup so they're recoverable, never silently deleted.
#
# Idempotent: if the orphans were already moved (or were never present),
# this is a no-op.

set -euo pipefail

: "${RUFINO_HOME:?must be set by upgrade.sh}"

CLAUDE_HOME="${HOME}/.claude"
ORPHAN_FILES=(
    "${CLAUDE_HOME}/hooks/rufino-memory-loop-init.sh"
    "${CLAUDE_HOME}/hooks/rufino-memory-loop-stop.sh"
    "${CLAUDE_HOME}/commands/remember.md"
)

FOUND=0
for f in "${ORPHAN_FILES[@]}"; do
    [ -e "$f" ] && FOUND=$((FOUND + 1))
done

if [ "$FOUND" -eq 0 ]; then
    echo "    No v0.0.2 orphan artifacts found in ${CLAUDE_HOME} — nothing to migrate."
    exit 0
fi

TS="$(date +%Y%m%d-%H%M%S)"
ORPHAN_DIR="${RUFINO_HOME}/backups/${TS}/v0.0.2-orphans"
mkdir -p "${ORPHAN_DIR}/hooks" "${ORPHAN_DIR}/commands"

MOVED=0
for f in "${ORPHAN_FILES[@]}"; do
    if [ -e "$f" ]; then
        dest_subdir="$(basename "$(dirname "$f")")"   # "hooks" or "commands"
        mv "$f" "${ORPHAN_DIR}/${dest_subdir}/"
        MOVED=$((MOVED + 1))
    fi
done

echo "    Moved ${MOVED} v0.0.2 orphan(s) to ${ORPHAN_DIR}"
echo "    These were un-slugged Memory loop artifacts superseded by per-vault names."
echo "    Re-install via \`rufino install-memory-loop\` if you still need them."
