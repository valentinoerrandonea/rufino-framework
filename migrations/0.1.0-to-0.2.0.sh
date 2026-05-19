#!/usr/bin/env bash
# Migration 0.1.0 → 0.2.0
#
# v0.2.0 introduces opt-in semantic embeddings with per-vault state at
# $RUFINO_HOME/state/vaults/<vault_slug>.yaml. Existing vaults default to
# embeddings disabled — they keep working in lexical mode without any
# user action. The semantic backend is materialized later via
# `rufino enable-embeddings --vault X`.
#
# Vault slug is derived from the memory_loop adapter directory name (one
# adapter per vault by convention).
set -euo pipefail
: "${RUFINO_HOME:?must be set by upgrade.sh}"

STATE_VAULTS_DIR="$RUFINO_HOME/state/vaults"
mkdir -p "$STATE_VAULTS_DIR"

if [ -d "$RUFINO_HOME/adapters/memory_loop" ]; then
  for adapter_dir in "$RUFINO_HOME/adapters/memory_loop"/*/; do
    [ -d "$adapter_dir" ] || continue
    slug="$(basename "$adapter_dir")"
    yaml_path="$STATE_VAULTS_DIR/$slug.yaml"
    if [ ! -f "$yaml_path" ]; then
      cat > "$yaml_path" <<INNER
vault_slug: $slug
embeddings:
  enabled: false
  backend: ollama
  model: nomic-embed-text
INNER
      echo "  wrote $yaml_path (embeddings disabled)"
    fi
  done
fi

echo "0.1.0 → 0.2.0 migration applied."
