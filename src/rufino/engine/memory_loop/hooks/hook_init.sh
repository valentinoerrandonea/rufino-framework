#!/usr/bin/env bash
# Rufino Memory loop — init hook (rendered at install time)

set -euo pipefail

VAULT="__VAULT_PATH__"

echo "## Vault: __VERTICAL_NAME__"
echo
echo "### perfil.md"
[ -f "$VAULT/perfil.md" ] && cat "$VAULT/perfil.md" || echo "(perfil not initialized)"
echo
echo "### preferencias.md"
[ -f "$VAULT/preferencias.md" ] && cat "$VAULT/preferencias.md" || echo "(preferences not initialized)"
echo
echo "### Reglas del vertical"
cat <<'RUFINO_RULES_EOF'
__RULES_CONCAT__
RUFINO_RULES_EOF
