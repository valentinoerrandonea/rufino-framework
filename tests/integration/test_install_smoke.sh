#!/usr/bin/env bash
# Integration smoke test of install.sh
# - runs installer twice (no RUFINO_VAULT → MCP skipped; with RUFINO_VAULT → MCP registered)
# - verifies binary works
# - verifies ~/.rufino layout, PATH rc line, and MCP registration
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

# --- First run: no RUFINO_VAULT → MCP should be skipped
HOME="$TMPHOME" \
    SHELL="/bin/bash" \
    RUFINO_HOME="$TMPHOME/.rufino" \
    PIPX_HOME="$TMPHOME/.local/pipx" \
    PIPX_BIN_DIR="$TMPHOME/.local/bin" \
    PIPX_MAN_DIR="$TMPHOME/.local/share/man" \
    bash "$REPO_DIR/install.sh"

# Layout
test -d "$TMPHOME/.rufino" || { echo "FAIL: ~/.rufino missing"; exit 1; }
test -d "$TMPHOME/.rufino/state" || { echo "FAIL: state/ missing"; exit 1; }
test -d "$TMPHOME/.rufino/adapters/ingest" || { echo "FAIL: adapters/ingest missing"; exit 1; }
test -f "$TMPHOME/.rufino/version" || { echo "FAIL: version file missing"; exit 1; }

# Binary
RUFINO_BIN="$TMPHOME/.local/bin/rufino"
test -x "$RUFINO_BIN" || { echo "FAIL: $RUFINO_BIN missing or not executable"; exit 1; }
"$RUFINO_BIN" version >/dev/null || { echo "FAIL: rufino version failed"; exit 1; }

# PATH rc line (we set SHELL=/bin/bash so install.sh writes to .bashrc)
grep -qF "# rufino-framework" "$TMPHOME/.bashrc" || { echo "FAIL: PATH marker comment not in .bashrc"; exit 1; }
grep -qF "$TMPHOME/.local/bin" "$TMPHOME/.bashrc" || { echo "FAIL: pipx bin dir not in .bashrc"; exit 1; }

# MCP NOT registered (RUFINO_VAULT was unset)
if [ -f "$TMPHOME/.claude.json" ]; then
    if jq -e '.mcpServers["ask-rufino"]' "$TMPHOME/.claude.json" >/dev/null 2>&1; then
        echo "FAIL: MCP registered without RUFINO_VAULT" >&2
        exit 1
    fi
fi

# --- Second run: with RUFINO_VAULT pointing at a real dir → MCP registered
VAULT="$TMPHOME/test-vault"
mkdir -p "$VAULT"

HOME="$TMPHOME" \
    SHELL="/bin/bash" \
    RUFINO_HOME="$TMPHOME/.rufino" \
    RUFINO_VAULT="$VAULT" \
    PIPX_HOME="$TMPHOME/.local/pipx" \
    PIPX_BIN_DIR="$TMPHOME/.local/bin" \
    PIPX_MAN_DIR="$TMPHOME/.local/share/man" \
    bash "$REPO_DIR/install.sh"

# MCP registered with the real vault path
test -f "$TMPHOME/.claude.json" || { echo "FAIL: .claude.json missing after register"; exit 1; }
REGISTERED_VAULT="$(jq -r '.mcpServers["ask-rufino"].args[2]' "$TMPHOME/.claude.json")"
test "$REGISTERED_VAULT" = "$VAULT" || { echo "FAIL: MCP vault arg is '$REGISTERED_VAULT', expected '$VAULT'"; exit 1; }
REGISTERED_CMD="$(jq -r '.mcpServers["ask-rufino"].command' "$TMPHOME/.claude.json")"
test "$REGISTERED_CMD" = "$RUFINO_BIN" || { echo "FAIL: MCP command is '$REGISTERED_CMD', expected '$RUFINO_BIN'"; exit 1; }

# Idempotency: PATH rc line not duplicated by second run
LINE_COUNT="$(grep -cF "# rufino-framework" "$TMPHOME/.bashrc")"
test "$LINE_COUNT" = "1" || { echo "FAIL: PATH marker duplicated ($LINE_COUNT times)"; exit 1; }

echo "==> OK: install smoke passed"
