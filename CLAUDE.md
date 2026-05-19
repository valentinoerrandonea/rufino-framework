# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

**Rufino Framework** — a meta-architecture for building personal knowledge vaults. A user runs `rufino bootstrap`, Claude Code interviews them, and at the end materializes a vault adapted to their vertical (study notes, 1:1s, finance, etc.). The framework ships *primitives* + a *wizard* that generates *adapters* against well-defined contracts.

Background reading when context demands it: `docs/superpowers/specs/2026-05-16-rufino-framework-design.md` (full design), `docs/primitives/*.md` (one-pagers per primitive), `docs/adapters/*.md` (the 4 adapter shapes).

## Common commands

Setup (local dev, editable):
```bash
./install.sh             # pipx install -e . + create ~/.rufino + register MCP
./upgrade.sh             # apply migrations/, refresh pipx venv
```

Tests:
```bash
pytest                              # all tests (pythonpath=src is auto-set via pyproject)
pytest tests/test_cli_process.py    # single file
pytest -k qa_worker                 # by keyword
pytest --cov=src --cov-report=term-missing
```

CLI (after install, or via `python -m rufino`):
```bash
rufino version
rufino bootstrap [--dry-run]                                  # --dry-run prints the system prompt; live launches `claude -p`
rufino materialize --spec FILE --vault X --claude-home Y --state-dir Z
rufino ingest <adapter_dir> --vault X --state-dir Y
rufino process <note> --vault X --mode {light|full|lint}      # full is stubbed (exits 2)
rufino output <adapter_dir> --vault X
rufino qa-poll --vault X --state-dir Y
rufino query "..." --vault X --mode {lexical|semantic|hybrid}
rufino mcp-server --vault X [--no-rebuild]
rufino install-memory-loop <adapter_dir> --vault X --claude-home Y
```

## Architecture

### The 6 primitives

Code lives under `src/rufino/engine/<primitive>/`. Each one has a one-pager in `docs/primitives/` and an implementation plan in `docs/superpowers/plans/`.

| Primitive | Shape | Module |
|---|---|---|
| **Ingest** — pull external data into the vault | Worker adapter | `engine/ingest/` |
| **Process** — augment raw notes (frontmatter, triples, tags, wikilinks) | Worker adapter | `engine/process/` |
| **Output** — generate derivatives (digests, reports, alerts) | Worker adapter | `engine/output/` (channels under `output/channels/`) |
| **Query** — unified read API (lexical / semantic / graph / faceted) | Service primitive (no adapter) | `engine/query/` |
| **Memory loop** — Claude Code integration (hooks, /remember, rules) | Vertical config | `engine/memory_loop/` |
| **Q&A loop** — questions only the user can answer | Question template (markdown) | `engine/qa/` |

The shape heterogeneity is intentional — see spec §4.3. Don't try to force uniform adapter shapes; new primitives should pick whatever fits.

### Top-level src layout

- `src/rufino/cli.py` — Click entry; one command per primitive plus `bootstrap` / `materialize` / `install-memory-loop` / `mcp-server`. The CLI is intentionally thin — orchestration lives in the engines.
- `src/rufino/engine/<primitive>/` — primitive implementations. Each has a `manifest.py` (parser/validator) + a `dispatcher.py` or `runner.py` (the executor) + helpers.
- `src/rufino/wizard/` — conversational bootstrap. `system_prompt_assembler.py` builds the prompt handed to `claude -p`; `spec_schema.py` validates the wizard's JSON output; `materializer.py` does the big-bang vault creation. `patterns/*.md` are vertical archetypes the wizard chooses from.
- `src/rufino/mcp_server/` — `ask-rufino` MCP server (stdio) wrapping the Query layer.
- `src/rufino/runtime/` — cross-cutting infra: `transaction_log.py` (the core of big-bang rollback), `secrets.py` (keyring), `scheduler.py` (launchd plists), `sandbox.py`, `prereq_checker.py`, `validator_base.py`.

### Transaction log = the load-bearing abstraction

Anything that mutates the filesystem, keychain, or launchd during materialization/installation goes through `runtime/transaction_log.py`. Every op records its inverse (`rmdir`, `delete`, `keychain_delete`, `plist_uninstall`, `rmdir_if_empty`, …). On any failure, `tx_log.rollback()` runs the inverses in reverse order. The framework's "big bang" guarantee (all-or-nothing bootstrap) is built on this.

New rollback handlers register via `register_rollback(name, fn)`. If you add a new disk-touching op, wrap it in `apply_and_log(tx_log, op=..., target=..., apply_fn=..., rollback=...)` — don't bypass it.

### `~/.rufino/` layout (created by installer)

```
~/.rufino/
├── version                 # current installed framework version
├── applied-migrations      # one filename per applied migration
├── state/                  # ingest cursors, dedup stores, qa worker state
├── backups/<timestamp>/    # snapshot before each upgrade
└── adapters/{ingest,process,output,memory_loop}/<adapter_name>/
```

User vaults live wherever the user chose at `bootstrap` time — they're independent of `~/.rufino/`. The framework writes to `~/.rufino/` for *its own* state; the vault is the user's data.

### Adapter contracts

Worker adapters (Ingest/Process/Output) all look like:
```
<adapter_dir>/
├── manifest.yaml      # required, schema per-primitive
├── prompt.md          # Process: required; Ingest emit_augmented: optional
├── template.md        # Output: required
└── transform.py       # optional, currently parsed but execution deferred
```

Each primitive's `manifest.py` parses and validates the adapter manifest before the dispatcher will run it. Validation errors block install; warnings log.

### Currently deferred (don't be surprised)

- `transform_hook` / `transform.py` — manifest accepts the field, runner does not yet invoke it.
- Ingest `output_mode: emit_augmented` — manifest parses, dispatcher not wired.
- `rufino process --mode full` (single-note) — exits with code 2. For batch processing, use `rufino process-batch`. Reviving the single-note path is out of scope for v0.1.0.
- `_NoopEmbeddings` in `cli.py` — placeholder embedder until the real Ollama wiring lands.

If you see one of these and assume it's broken, check the plan docs first.

### Deferred for v0.2+

These are tracked rough edges shipped in v0.1.0 that we explicitly chose not to fix yet. If you hit one, check it's still on the list before opening a new ticket:

- **Unbounded stdout/stderr capture** in `engine/process/batch/runner_helper.py` — a misbehaving `claude` worker could OOM the parent process. Marked with a `TODO(v0.2)`.
- **Advisory lock per vault** — `rufino process-batch` and `qa-resume` can be invoked concurrently against the same vault and stomp each other's run dirs. v0.2 will take a flock on `<vault>/.rufino/lock`.
- **Worker ID padding** — worker IDs render as `w001`/`w002`/… today, capped at three digits. A corpus producing >999 workers will collide. v0.2 widens to `:04d`.
- **`transform_hook` execution** — accepted by the manifest parser, ignored by the runner. See `docs/primitives/process.md`.
- **Ingest `output_mode: emit_augmented`** — manifest parses it, dispatcher does not branch on it.
- **Single-note `rufino process --mode full`** — exits with code 2. Use `process-batch` instead; the single-note path is out of scope until the planner has a "batch of one" mode.

## Versioning + migrations

`upgrade.sh` is keyed on `rufino version`, which reads `src/rufino/version.py:VERSION`. **Code changes without a version bump are invisible to `upgrade.sh`** — it'll print `Already at X. Nothing to do.` after `git pull`. Bump `VERSION` *and* `pyproject.toml`'s `version` together when releasing.

Migrations are bash scripts in `migrations/`, named `<from>-to-<to>.sh`. They:
- run **in lexicographic order** (so name them in semver order)
- must be **idempotent** (`upgrade.sh` may re-run after a partial failure)
- run **against the new code** (the pipx reinstall happens before migrations) — they can't import the old API; read state files directly off disk or convert lazily on next normal run
- get tracked one-per-line in `~/.rufino/applied-migrations`
- have `$RUFINO_HOME` available

The directory contains markers for prior version transitions (`0.0.2-to-0.0.3.sh`, `0.0.3-to-0.1.0.sh`). New migrations should follow the contract in `migrations/README.md`.

## Test conventions

- `tests/conftest.py` provides `tmp_vault` and `tmp_rufino_home` fixtures — use them rather than rolling your own tmp setup.
- Test files mirror the module structure (`test_ingest_*`, `test_process_*`, `test_qa_*`, `test_wizard_*`, etc.).
- `tests/integration/` exists for cross-engine tests; unit tests live flat under `tests/`.
- Many tests assert on `TransactionLog` rollback behavior — when you add a new disk-touching op, add a test that forces failure and verifies the rollback runs cleanly.

## Things to know before editing

- **The CLI is a façade.** `src/rufino/cli.py` should stay thin — actual orchestration belongs in the engine module's dispatcher/runner. If you find yourself adding branching logic in `cli.py`, push it down.
- **`emit_augmented`, `transform_hook`, `--mode full`, and the real embedder are deferred on purpose.** Don't implement them as part of unrelated work — they each have a referenced plan.
- **Adapter manifests are the API contract** between the wizard and the engine. Changing a manifest schema means updating the parser + validator + every adapter the wizard generates + the docs in `docs/primitives/`.
- **Pipx + uv backend gotcha** documented in `install.sh` step 3: `pipx install --force` fails on the uv backend when the venv already exists. The installer checks `pipx list --short` and uses `reinstall` when present, `install -e` when absent. Preserve this pattern if you touch the installers.
- **The wizard runs Claude.** `rufino bootstrap` shells out to the `claude` CLI with a system prompt and a restricted `--allowedTools` set. If you need to test the prompt without launching Claude, use `--dry-run`.
