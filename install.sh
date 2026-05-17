#!/usr/bin/env bash
# Rufino Framework installer
# Idempotent: safe to re-run.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUFINO_HOME="${RUFINO_HOME:-$HOME/.rufino}"
CLAUDE_HOME="${CLAUDE_HOME:-$HOME/.claude}"

echo "==> Rufino Framework installer"
echo "    repo:        $REPO_DIR"
echo "    RUFINO_HOME: $RUFINO_HOME"
echo "    CLAUDE_HOME: $CLAUDE_HOME"
echo

# --- Step 1: Check Python
if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 not found. Install Python 3.11+ first." >&2
    exit 1
fi
PY_VERSION="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
echo "    python3:     $PY_VERSION"

# --- Step 2: Check pipx (PEP 668 friendly Python app installer)
if ! command -v pipx >/dev/null 2>&1; then
    cat >&2 <<'EOF'
ERROR: pipx not found. Install it first:

  macOS:  brew install pipx && pipx ensurepath
  Linux:  python3 -m pip install --user pipx && python3 -m pipx ensurepath

Then open a new shell and re-run ./install.sh.
EOF
    exit 1
fi

# --- Step 3: Install Rufino in an isolated pipx venv (idempotent via --force)
echo "==> Installing Rufino into pipx venv"
pipx install --force -e "$REPO_DIR"

# --- Step 4: Resolve where pipx put the rufino binary
if [ -n "${PIPX_BIN_DIR:-}" ]; then
    BIN_DIR="$PIPX_BIN_DIR"
else
    BIN_DIR="$(pipx environment --value PIPX_BIN_DIR 2>/dev/null || echo "$HOME/.local/bin")"
fi
RUFINO_BIN="$BIN_DIR/rufino"

if [ ! -x "$RUFINO_BIN" ]; then
    echo "ERROR: $RUFINO_BIN missing after pipx install" >&2
    exit 1
fi

# --- Step 5: Ensure pipx bin dir is on PATH
SHELL_NAME="$(basename "$SHELL")"
case "$SHELL_NAME" in
    bash) RC="$HOME/.bashrc" ;;
    zsh)  RC="$HOME/.zshrc" ;;
    *)    RC="" ;;
esac

PATH_LINE="export PATH=\"$BIN_DIR:\$PATH\"  # rufino-framework"

if [ -n "$RC" ]; then
    if ! grep -qF "$BIN_DIR" "$RC" 2>/dev/null; then
        echo "==> Adding $BIN_DIR to PATH in $RC"
        echo "" >> "$RC"
        echo "$PATH_LINE" >> "$RC"
    else
        echo "    PATH already configured in $RC (skip)"
    fi
else
    echo "    WARN: unknown shell '$SHELL_NAME'; add manually:" >&2
    echo "    $PATH_LINE" >&2
fi

# --- Step 6: Create ~/.rufino structure
echo "==> Creating $RUFINO_HOME structure"
mkdir -p "$RUFINO_HOME/state"
mkdir -p "$RUFINO_HOME/backups"
mkdir -p "$RUFINO_HOME/adapters/ingest"
mkdir -p "$RUFINO_HOME/adapters/process"
mkdir -p "$RUFINO_HOME/adapters/output"
mkdir -p "$RUFINO_HOME/adapters/memory_loop"
mkdir -p "$CLAUDE_HOME/hooks"
mkdir -p "$CLAUDE_HOME/commands"

# Track installed version
"$RUFINO_BIN" version > "$RUFINO_HOME/version"
echo "    version recorded: $(cat "$RUFINO_HOME/version")"

# --- Step 7: Register MCP server
CLAUDE_JSON="$HOME/.claude.json"
if command -v jq >/dev/null 2>&1; then
    if [ ! -f "$CLAUDE_JSON" ]; then
        echo "{}" > "$CLAUDE_JSON"
    fi
    if ! jq -e '.mcpServers["ask-rufino"]' "$CLAUDE_JSON" >/dev/null 2>&1; then
        echo "==> Registering MCP server ask-rufino in $CLAUDE_JSON"
        TMP="$(mktemp)"
        jq --arg cmd "$RUFINO_BIN" \
           '.mcpServers["ask-rufino"] = {
                command: $cmd,
                args: ["mcp-server", "--vault", "<set RUFINO_VAULT env>"]
            }' "$CLAUDE_JSON" > "$TMP"
        mv "$TMP" "$CLAUDE_JSON"
    else
        echo "    MCP server already registered (skip)"
    fi
else
    echo "    WARN: jq not installed — skipping MCP registration." >&2
    echo "    Add manually to $CLAUDE_JSON under .mcpServers" >&2
fi

echo
echo "==> Done."
echo
echo "Listo. Para empezar, abrí una shell nueva (o source $RC) y corré:"
echo "    rufino bootstrap"
