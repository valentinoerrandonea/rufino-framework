# Migrations

Each migration script is a bash file named `<from>-to-<to>.sh` (e.g. `0.0.1-to-0.1.0.sh`).

Migrations are applied in **lexicographic order** of filename, so always
prefix with semver-ordered names. The applied set is tracked in
`~/.rufino/applied-migrations` (one filename per line).

Each migration MUST be idempotent — `upgrade.sh` may be re-run after a
partial failure, and a migration that already ran half-way should be safe
to re-execute.

## Execution order

`upgrade.sh` runs in this order:
1. Backup `~/.rufino/` to `~/.rufino/backups/<timestamp>/`
2. `pipx install --force -e $REPO_DIR` (reinstall — code is now at target version)
3. Apply migrations
4. Bump `~/.rufino/version`

Migrations therefore run **against the new code**. If a migration needs to read
old in-memory state via the old API, it can't — read state files directly off
disk instead, or convert state lazily on next normal run.

## Version coupling

The `INSTALLED → CURRENT` comparison is keyed off the `rufino version` output
(read from `src/rufino/version.py`'s `VERSION` constant). Code changes that
do NOT bump `VERSION` are invisible to `upgrade.sh` — it will hit the
`Already at X. Nothing to do.` branch even after `git pull`. Bump `VERSION`
+ `pyproject.toml`'s `version` together when releasing.

## Example migration

`migrations/0.0.1-to-0.1.0.sh`:
```bash
#!/usr/bin/env bash
set -euo pipefail
# $RUFINO_HOME is exported by upgrade.sh
: "${RUFINO_HOME:?must be set by upgrade.sh}"
if [ -f "$RUFINO_HOME/old-name.json" ]; then
    mv "$RUFINO_HOME/old-name.json" "$RUFINO_HOME/new-name.json"
fi
```

No migrations yet — directory is initially empty.
