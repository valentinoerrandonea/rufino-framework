#!/usr/bin/env bash
# Rufino Framework — auto-detect hook
# Si el vault apuntado por RUFINO_VAULT está vacío, sugiere `rufino bootstrap`.
# Silencioso cuando hay notas reales o cuando no hay vault configurado.

set -euo pipefail

VAULT="${RUFINO_VAULT:-}"
if [ -z "$VAULT" ] || [ ! -d "$VAULT" ]; then
    exit 0
fi

# "Empty" = no .md files except possibly perfil.md / preferencias.md
NOTE_COUNT=$(
    find "$VAULT" -name "*.md" \
        -not -name "perfil.md" \
        -not -name "preferencias.md" \
        2>/dev/null \
        | wc -l \
        | tr -d ' '
)

if [ "$NOTE_COUNT" = "0" ]; then
    echo "RUFINO HINT: Tu vault está vacío. Para armar tu sistema corré: rufino bootstrap"
fi
