# Multi-vault support — design

**Status:** approved 2026-05-18
**Author:** Val + Claude
**Tracking:** unblocks testing the framework with more than one vault on a single machine.

## Problem

v0.0.2 was single-vault de facto. Three places hardcoded names that prevented running `materialize` twice on the same machine:

1. `engine/memory_loop/installer.py` writes `rufino-memory-loop-init.sh`, `rufino-memory-loop-stop.sh`, `commands/remember.md` with fixed names. A second install raises `InstallationError("already installed")`.
2. `cli.py:materialize_cmd` registers the MCP server with the fixed name `ask-rufino` — a second `materialize` overwrites the first vault's entry in `~/.claude.json`.
3. `wizard/materializer.py:materialize` unconditionally calls `install_memory_loop`. Users that don't want Claude Code hooks intercepting their conversations have no opt-out.

Together: a user cannot have two vaults coexist, and cannot bootstrap a vault without giving Rufino hooks into Claude Code.

## Design

### Per-vault slug

A single helper computes a stable slug from the vault path:

```python
# runtime/vault_slug.py
def compute_vault_slug(vault_path: Path) -> str:
    name = vault_path.expanduser().resolve().name
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if not slug:
        raise ValueError(...)
    return slug
```

Slug is derived from `vault_path.name`, not from `vertical_name` — two vaults can legitimately share a vertical (`study-2024` and `study-2025` both `vertical=facultad`) and must coexist.

### Per-vault artifact names

| Artifact | Old | New |
|---|---|---|
| Init hook | `hooks/rufino-memory-loop-init.sh` | `hooks/rufino-memory-loop-init-<slug>.sh` |
| Stop hook | `hooks/rufino-memory-loop-stop.sh` | `hooks/rufino-memory-loop-stop-<slug>.sh` |
| Command | `commands/remember.md` → `/remember` | `commands/remember-<slug>.md` → `/remember-<slug>` |
| MCP server | `ask-rufino` | `ask-rufino-<slug>` |

The existing "refuse to clobber prior install" collision check stays. With slugs in the filename, the only collision is "re-installing the *same* vault twice" — which is still the correct case to refuse (rollback would destroy the previous good state).

### Optional hook installation

`materialize()` gains a keyword arg `install_hooks: bool = False`. When `False`, the adapter manifest is still written under `~/.rufino/adapters/memory_loop/<vertical>/` (cheap, useful if the user enables hooks later) but `install_memory_loop` is not called.

The CLI exposes the flag as `--install-hooks/--no-install-hooks`, default **no-install** — conservative because hooks intercept Claude Code conversations and that should be opt-in.

The MCP server is always registered. It is a read-only path into the vault and is the main consumer-facing integration; there is no reason to make it optional.

### Wizard updates

The wizard must:
- Ask the user whether to install hooks before invoking `rufino materialize`.
- Pass the matching flag in the invocation.

Two minimal edits to the wizard prompt:
- `checklist.md` gets a new item: "User decidió si activar la captura de conversaciones de Claude Code".
- `operative_rules.md` gets a rule: "Antes del big bang, preguntá explícitamente si quiere que el framework capture y analice las conversaciones de Claude Code en este vault. Es opcional. Pasalo a `rufino materialize` como `--install-hooks` o `--no-install-hooks`."

The system prompt's section 9 currently advertises hooks as a default-on feature; that needs reframing as opt-in.

## Out of scope

- **Migration for users on v0.0.2:** there are no users yet; `VERSION` is `0.0.2` and the install hasn't been distributed.
- **Smart `/remember` that picks the active vault:** keeping `/remember-<slug>` per vault for now — simpler, no ambiguity.
- **Renaming `vertical_name` to something more vault-specific:** orthogonal change.
- **Uninstall command:** referenced by the "uninstall first" error but not implemented; tracked separately.

## Test plan

- `compute_vault_slug` unit tests (path normalization, edge cases).
- `install_memory_loop` writes filenames containing the slug; two different vaults coexist; same vault twice still raises.
- `materialize(install_hooks=False)` skips `install_memory_loop` but still creates the vault skeleton and writes the adapter manifest.
- `rufino materialize` registers MCP server name `ask-rufino-<slug>` and supports `--install-hooks/--no-install-hooks`.
- Existing tests updated to assert on the new names.
