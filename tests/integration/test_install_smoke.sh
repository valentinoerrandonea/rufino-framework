#!/usr/bin/env bash
# Integration smoke test of install.sh
# - runs installer with isolated HOME + isolated pipx state
# - verifies binary works
# - verifies ~/.rufino structure created
# Does NOT touch the user's real ~/.claude.json, ~/.rufino, or ~/.local/pipx
#
# Requires: pipx on PATH (brew install pipx).

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

if ! command -v pipx >/dev/null 2>&1; then
    echo "SKIP: pipx not installed (brew install pipx)" >&2
    exit 0
fi

TMPHOME="$(mktemp -d)"
trap 'rm -rf "$TMPHOME"' EXIT

echo "==> Smoke test using HOME=$TMPHOME"

HOME="$TMPHOME" \
    SHELL="/bin/bash" \
    RUFINO_HOME="$TMPHOME/.rufino" \
    CLAUDE_HOME="$TMPHOME/.claude" \
    PIPX_HOME="$TMPHOME/.local/pipx" \
    PIPX_BIN_DIR="$TMPHOME/.local/bin" \
    PIPX_MAN_DIR="$TMPHOME/.local/share/man" \
    bash "$REPO_DIR/install.sh"

# Verify structure
test -d "$TMPHOME/.rufino" || { echo "FAIL: ~/.rufino missing"; exit 1; }
test -d "$TMPHOME/.rufino/state" || { echo "FAIL: state/ missing"; exit 1; }
test -f "$TMPHOME/.rufino/version" || { echo "FAIL: version file missing"; exit 1; }

# Verify the rufino binary pipx created actually runs
RUFINO_BIN="$TMPHOME/.local/bin/rufino"
test -x "$RUFINO_BIN" || { echo "FAIL: $RUFINO_BIN missing or not executable"; exit 1; }
"$RUFINO_BIN" version >/dev/null || { echo "FAIL: rufino version failed"; exit 1; }

echo "==> OK: install smoke passed"
