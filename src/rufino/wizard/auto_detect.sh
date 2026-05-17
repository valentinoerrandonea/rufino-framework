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
# `-print -quit` stops find on the first match — O(1) work for non-empty vaults,
# avoids `wc -l` enumerating thousands of notes only to discard the count.
FIRST_NOTE=$(
    find "$VAULT" \
        -type f \
        -name "*.md" \
        -not -name "perfil.md" \
        -not -name "preferencias.md" \
        -print -quit 2>/dev/null
)

if [ -z "$FIRST_NOTE" ]; then
    echo "RUFINO HINT: Tu vault está vacío. Para armar tu sistema corré: rufino bootstrap"
fi
