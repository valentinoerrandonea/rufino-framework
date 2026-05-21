#!/usr/bin/env bash
# Migration 0.2.1 → 0.3.0
#
# v0.3 changes are purely additive:
#   - compression_floor: optional field on ProcessSpec / manifest, default None
#   - author_writes: new key in ConsolidationPlan, defaults to [] when missing
#   - multimodal: new opt-in flag on process-batch (does not affect existing runs)
#
# No state migration required. Existing adapters and run state remain valid.
set -euo pipefail
: "${RUFINO_HOME:?must be set by upgrade.sh}"

echo "0.2.1 → 0.3.0: no state migration required (additive changes only)."
