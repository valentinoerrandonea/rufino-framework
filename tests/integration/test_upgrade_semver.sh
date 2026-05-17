#!/usr/bin/env bash
# Smoke: upgrade.sh must refuse to downgrade.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

export RUFINO_HOME="$TMP/.rufino"
mkdir -p "$RUFINO_HOME"
echo "9.9.9" > "$RUFINO_HOME/version"  # pretend a newer version is installed

# Stub a rufino binary that returns the current source version.
STUB_BIN_DIR="$TMP/bin"
mkdir -p "$STUB_BIN_DIR"
CURRENT_VERSION="$(grep -E '^VERSION' "$REPO_DIR/src/rufino/version.py" | head -1 | cut -d'"' -f2)"
cat > "$STUB_BIN_DIR/rufino" <<EOF
#!/bin/bash
[ "\$1" = "version" ] && echo "$CURRENT_VERSION"
EOF
chmod +x "$STUB_BIN_DIR/rufino"
export PIPX_BIN_DIR="$STUB_BIN_DIR"

# Stub pipx so upgrade.sh doesn't actually try to reinstall.
PATH="$TMP/fake-tools:$PATH"
mkdir -p "$TMP/fake-tools"
cat > "$TMP/fake-tools/pipx" <<'EOF'
#!/bin/bash
exit 0
EOF
chmod +x "$TMP/fake-tools/pipx"
export PATH

rc=0
output="$("$REPO_DIR/upgrade.sh" 2>&1)" || rc=$?
echo "$output" | head -10

[ "$rc" -ne 0 ] || { echo "FAIL: upgrade.sh allowed downgrade (exit $rc)"; exit 1; }
echo "$output" | grep -qi "downgrade" || { echo "FAIL: missing downgrade message"; exit 1; }
echo "OK: downgrade blocked"

# Verify RUFINO_FORCE=1 override works.
rc=0
RUFINO_FORCE=1 output="$("$REPO_DIR/upgrade.sh" 2>&1)" || rc=$?
echo "$output" | grep -qi "forced downgrade" || {
    echo "FAIL: --force did not produce expected message"
    echo "$output"
    exit 1
}
echo "OK: forced downgrade allowed with RUFINO_FORCE=1"
