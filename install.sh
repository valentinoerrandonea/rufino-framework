#!/usr/bin/env bash
# Rufino Framework installer
# Idempotent: safe to re-run.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUFINO_HOME="${RUFINO_HOME:-$HOME/.rufino}"

echo "==> Rufino Framework installer"
echo "    repo:        $REPO_DIR"
echo "    RUFINO_HOME: $RUFINO_HOME"
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

# --- Step 3: Install Rufino in an isolated pipx venv (idempotent)
# pipx install --force can fail on the uv backend if the venv exists from a
# prior session ("Not removing existing venv ... was not created in this
# session"). Use reinstall when already present.
if pipx list --short 2>/dev/null | awk '{print $1}' | grep -qx 'rufino-framework'; then
    echo "==> Rufino already installed — rebuilding via pipx reinstall"
    pipx reinstall rufino-framework
else
    echo "==> Installing Rufino into pipx venv"
    pipx install -e "$REPO_DIR"
fi

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

PATH_MARKER="# rufino-framework"
PATH_LINE="export PATH=\"$BIN_DIR:\$PATH\"  $PATH_MARKER"

if [ -n "$RC" ]; then
    if ! grep -qF "$PATH_MARKER" "$RC" 2>/dev/null; then
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
# ($CLAUDE_HOME subdirs like hooks/commands are created lazily by
#  the memory-loop installer when an adapter is installed — not seeded here.)
echo "==> Creating $RUFINO_HOME structure"
mkdir -p "$RUFINO_HOME/state"
mkdir -p "$RUFINO_HOME/backups"
mkdir -p "$RUFINO_HOME/adapters/ingest"
mkdir -p "$RUFINO_HOME/adapters/process"
mkdir -p "$RUFINO_HOME/adapters/output"
mkdir -p "$RUFINO_HOME/adapters/memory_loop"

# Track installed version
"$RUFINO_BIN" version > "$RUFINO_HOME/version"
echo "    version recorded: $(cat "$RUFINO_HOME/version")"

# --- Step 7: Register MCP server (only if we know a real vault path)
# The MCP server needs a real --vault path; Click rejects --vault when
# the directory does not exist. If RUFINO_VAULT is set in the environment
# we use it; otherwise we skip and let `rufino bootstrap` finish the
# registration once the user has materialized a vault.
CLAUDE_JSON="$HOME/.claude.json"
MCP_REGISTERED="no"
if command -v jq >/dev/null 2>&1; then
    if [ -n "${RUFINO_VAULT:-}" ] && [ -d "$RUFINO_VAULT" ]; then
        if [ ! -f "$CLAUDE_JSON" ]; then
            echo "{}" > "$CLAUDE_JSON"
        fi
        # Derive a per-vault MCP server name so multiple vaults can coexist
        # in ~/.claude.json (mirrors rufino.runtime.vault_slug.compute_vault_slug).
        VAULT_SLUG="$(basename "$RUFINO_VAULT" | tr '[:upper:]' '[:lower:]' \
            | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//')"
        if [ -z "$VAULT_SLUG" ]; then
            echo "    WARN: could not derive slug from $(basename "$RUFINO_VAULT") — skipping." >&2
        else
            SERVER_NAME="ask-rufino-${VAULT_SLUG}"
            CURRENT_VAULT="$(jq -r --arg n "$SERVER_NAME" '.mcpServers[$n].args[2] // ""' "$CLAUDE_JSON" 2>/dev/null || echo "")"
            if [ "$CURRENT_VAULT" = "$RUFINO_VAULT" ]; then
                echo "    MCP server $SERVER_NAME already registered for $RUFINO_VAULT (skip)"
                MCP_REGISTERED="already"
            else
                if [ -n "$CURRENT_VAULT" ]; then
                    echo "==> Updating MCP server $SERVER_NAME vault: $CURRENT_VAULT → $RUFINO_VAULT"
                else
                    echo "==> Registering MCP server $SERVER_NAME in $CLAUDE_JSON"
                fi
                TMP="$(mktemp)"
                jq --arg cmd "$RUFINO_BIN" --arg vault "$RUFINO_VAULT" --arg name "$SERVER_NAME" \
                   '.mcpServers = (.mcpServers // {}) |
                    .mcpServers[$name] = {
                        command: $cmd,
                        args: ["mcp-server", "--vault", $vault]
                    }' "$CLAUDE_JSON" > "$TMP"
                mv "$TMP" "$CLAUDE_JSON"
                MCP_REGISTERED="yes"
            fi
        fi
    else
        echo "    MCP server NOT registered — RUFINO_VAULT not set or not a directory." >&2
        echo "    Run \`rufino bootstrap\` to materialize a vault; the wizard will register the MCP server at the end." >&2
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
