#!/usr/bin/env bash
# Migration 0.0.3 → 0.1.0
#
# v0.1.0 adds `rufino process-batch` and one optional field (`batch_size`)
# to the adapter manifest schema. Vault-side adjustment (adding
# `.rufino/runs/` to the vault's .gitignore) happens lazily at the first
# process-batch run per vault, so this migration does NOT enumerate vaults.
set -euo pipefail

echo "0.0.3 → 0.1.0: no state changes required."
