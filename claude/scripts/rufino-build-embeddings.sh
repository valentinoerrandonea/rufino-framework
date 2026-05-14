#!/usr/bin/env bash
# Thin wrapper para rufino-build-embeddings.py.
# Carga env desde ~/.config/rufino/env si existe; chequea Python deps; ejecuta.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${RUFINO_ENV_FILE:-$HOME/.config/rufino/env}"

if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$ENV_FILE"
fi

if [[ -z "${RUFINO_VAULT_PATH:-}" ]]; then
  echo "ERROR: RUFINO_VAULT_PATH no está seteado (chequeá $ENV_FILE)." >&2
  exit 2
fi

if ! python3 -c "import sqlite_vec" >/dev/null 2>&1; then
  echo "Instalando sqlite-vec (Python)..." >&2
  pip3 install --quiet --break-system-packages sqlite-vec || pip3 install --quiet sqlite-vec
fi

exec python3 "$SCRIPT_DIR/rufino-build-embeddings.py" "$@"
