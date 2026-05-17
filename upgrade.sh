#!/usr/bin/env bash
# Rufino Framework upgrade
# - reads installed version from ~/.rufino/version
# - compares to current repo version
# - backs up ~/.rufino/ to ~/.rufino/backups/<timestamp>/
# - runs migrations/<version>.sh in order

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUFINO_HOME="${RUFINO_HOME:-$HOME/.rufino}"
VERSION_FILE="$RUFINO_HOME/version"

if [ ! -f "$VERSION_FILE" ]; then
    echo "ERROR: $VERSION_FILE not found. Run ./install.sh first." >&2
    exit 1
fi

if ! command -v pipx >/dev/null 2>&1; then
    echo "ERROR: pipx not found. Install it and re-run." >&2
    exit 1
fi

if [ -n "${PIPX_BIN_DIR:-}" ]; then
    BIN_DIR="$PIPX_BIN_DIR"
else
    BIN_DIR="$(pipx environment --value PIPX_BIN_DIR 2>/dev/null || echo "$HOME/.local/bin")"
fi
RUFINO_BIN="$BIN_DIR/rufino"

INSTALLED="$(cat "$VERSION_FILE")"
CURRENT="$("$RUFINO_BIN" version 2>/dev/null || python3 -c 'from rufino.version import VERSION; print(VERSION)')"

echo "==> Rufino Framework upgrade"
echo "    installed: $INSTALLED"
echo "    target:    $CURRENT"

if [ "$INSTALLED" = "$CURRENT" ]; then
    echo "==> Already at $CURRENT. Nothing to do."
    exit 0
fi

# --- Backup
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="$RUFINO_HOME/backups/$TIMESTAMP"
echo "==> Backing up $RUFINO_HOME to $BACKUP_DIR"
mkdir -p "$BACKUP_DIR"
# Exclude backups/ to avoid recursive copy
find "$RUFINO_HOME" -maxdepth 1 -mindepth 1 ! -name backups -exec cp -r {} "$BACKUP_DIR/" \;

# --- Reinstall Python package via pipx
echo "==> Reinstalling Rufino into pipx venv"
pipx install --force -e "$REPO_DIR"

# --- Apply migrations in order
echo "==> Applying migrations"
MIGRATIONS_DIR="$REPO_DIR/migrations"
APPLIED_FILE="$RUFINO_HOME/applied-migrations"
touch "$APPLIED_FILE"

for migration in "$MIGRATIONS_DIR"/*.sh; do
    [ -f "$migration" ] || continue  # no migrations yet
    name="$(basename "$migration")"
    if grep -qF "$name" "$APPLIED_FILE"; then
        echo "    skip $name (already applied)"
        continue
    fi
    echo "    applying $name"
    bash "$migration"
    echo "$name" >> "$APPLIED_FILE"
done

# --- Update version marker
echo "$CURRENT" > "$VERSION_FILE"

echo "==> Upgrade complete: $INSTALLED → $CURRENT"
echo "    Backup: $BACKUP_DIR"
