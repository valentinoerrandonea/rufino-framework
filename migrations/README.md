# Migrations

Each migration script is a bash file named `<from>-to-<to>.sh` (e.g. `0.0.1-to-0.1.0.sh`).

Migrations are applied in **lexicographic order** of filename, so always
prefix with semver-ordered names. The applied set is tracked in
`~/.rufino/applied-migrations` (one filename per line).

Each migration MUST be idempotent — `upgrade.sh` may be re-run after a
partial failure, and a migration that already ran half-way should be safe
to re-execute.

## Example migration

`migrations/0.0.1-to-0.1.0.sh`:
```bash
#!/usr/bin/env bash
set -euo pipefail
# Example: rename a state file
if [ -f "$HOME/.rufino/old-name.json" ]; then
    mv "$HOME/.rufino/old-name.json" "$HOME/.rufino/new-name.json"
fi
```

No migrations yet — directory is initially empty.
