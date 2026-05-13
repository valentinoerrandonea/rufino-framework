#!/usr/bin/env bash
# Setup del MCP server `ask-rufino`.
# 1) Copia el código del repo a ~/.claude/mcp/ask-rufino/
# 2) npm install
# 3) Muestra el JSON block para registrar en ~/.claude.json

set -euo pipefail

REPO_DIR="${RUFINO_REPO_DIR:-$HOME/Files/rufino}"
SRC_DIR="$REPO_DIR/claude/mcp/ask-rufino"
DEST_DIR="$HOME/.claude/mcp/ask-rufino"
VAULT_PATH="${RUFINO_VAULT_PATH:-/Users/val/Files/vaultlentino}"

echo "[setup-mcp-ask-rufino] origen: $SRC_DIR"
echo "[setup-mcp-ask-rufino] destino: $DEST_DIR"
echo "[setup-mcp-ask-rufino] vault: $VAULT_PATH"

if [[ ! -d "$SRC_DIR" ]]; then
  echo "ERROR: no existe $SRC_DIR" >&2
  exit 1
fi

mkdir -p "$DEST_DIR"

# rsync con fallback a cp.
if command -v rsync >/dev/null 2>&1; then
  rsync -a --delete \
    --exclude='node_modules' \
    --exclude='.git' \
    "$SRC_DIR/" "$DEST_DIR/"
else
  echo "[setup-mcp-ask-rufino] rsync no disponible, usando cp"
  rm -rf "$DEST_DIR"
  mkdir -p "$DEST_DIR"
  cp -R "$SRC_DIR/." "$DEST_DIR/"
fi

echo "[setup-mcp-ask-rufino] archivos copiados:"
ls -la "$DEST_DIR"

echo ""
echo "[setup-mcp-ask-rufino] corriendo npm install..."
cd "$DEST_DIR"
npm install --omit=dev --no-audit --no-fund || {
  echo "WARN: npm install falló. El test mode sigue funcionando sin SDK." >&2
}

echo ""
echo "[setup-mcp-ask-rufino] test mode:"
node "$DEST_DIR/index.js" --test 2>/dev/null | head -20 || echo "(test falló, revisar manualmente)"

cat <<EOF

============================================================
PASO MANUAL: registrar en ~/.claude.json
============================================================
Pegá este bloque dentro del objeto "mcpServers" en ~/.claude.json:

"ask-rufino": {
  "command": "node",
  "args": ["$DEST_DIR/index.js"],
  "env": {
    "RUFINO_VAULT_PATH": "$VAULT_PATH"
  }
}

Después reiniciá Claude Code y verificá con:
  claude mcp list

EOF
