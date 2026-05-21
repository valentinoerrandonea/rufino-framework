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
rufino bootstrap [--dry-run]                                  # --dry-run prints the system prompt; live launches interactive `claude --system-prompt ... --allowedTools ... -- "<kickoff>"`
rufino materialize --spec FILE --vault X --claude-home Y --state-dir Z
rufino ingest <adapter_dir> --vault X --state-dir Y
rufino process <note> --vault X --mode {light|full|lint}      # mode=full staged as tempdir-of-one and delegated to run_batch(workers=1, batch_size=1)
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
- `src/rufino/wizard/` — conversational bootstrap. `system_prompt_assembler.py` builds the prompt handed to interactive `claude` (with `--system-prompt` + restricted `--allowedTools`); `spec_schema.py` validates the wizard's JSON output; `materializer.py` does the big-bang vault creation. `patterns/*.md` are vertical archetypes the wizard chooses from.
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
└── transform.py       # optional — invoked between stages with graceful-degrade on failure (v0.2.0+)
```

Each primitive's `manifest.py` parses and validates the adapter manifest before the dispatcher will run it. Validation errors block install; warnings log.

### What landed in v0.2.0 (no longer deferred)

The big-bang v0.2.0 release closed the 12 gaps that shipped half-wired in v0.1.0:

- `transform_hook` / `transform.py` — runner invokes it between fetch/write (Ingest) and VALIDATE/CONSOLIDATE (Process); failures fall back to the original record.
- Ingest `output_mode: emit_augmented` — streams records directly to Process in light mode.
- `rufino process --mode full` (single-note) — staged as a tempdir-of-one and delegated to `run_batch(workers=1, batch_size=1)`.
- Semantic embedder — opt-in via `rufino enable-embeddings --vault X`; OllamaEmbedder + cross-encoder re-rank for hybrid. Disabled by default; per-vault state at `~/.rufino/state/vaults/<slug>.yaml`.
- Forward graph traversal — `GraphBackend.traverse(reverse=False)` operates at `depth=1`.
- Scheduler real — `rufino install-ingest` materializes the cron to `launchd` (macOS) / `cron` (Linux).
- Vault advisory lock — `runtime/vault_lock.py`; concurrent `process-batch`/`qa-resume` against the same vault fails the second caller fast.
- Bounded I/O — worker stdout/stderr capped at `MAX_OUTPUT_BYTES` (1MB).
- Worker IDs widened to `:04d`.

### What landed in v0.3.0 (corpus quality)

Closed the four critical gaps surfaced by the facultad vault bootstrap session (2026-05-20):

- **`compression_floor` on ProcessSpec** — optional float (0.0–1.0) that injects a fidelity constraint into the worker preamble and triggers a warning when the augmented body falls below the ratio. Adapters that prioritise study/reference fidelity should set this to ~0.9. Defaults to `None` (v0.2.x behavior).
- **`author_writes` in ConsolidationPlan** — the consolidator now emits enriched author notes (bio + obra + por qué importa) in addition to concept stubs. The committer writes them under `autores/<slug>.md`. Backward compatible with v0.2.x plans (`author_writes` defaults to `[]` when missing).
- **Enriched concept bodies** — the consolidator preamble now requires definición + contexto + ejemplo + relacionado-con + formulado-por for every `concept_write` content, drawing from the augmented notes where the concept appears. No more `_Expandi con tu propia explicacion_` placeholders.
- **`--multimodal` flag on process-batch** — opt-in. Converts DOCX/PPTX to PDF via `soffice --headless --convert-to pdf`, preserving embedded diagrams/images for the worker (which reads the PDF natively with vision). Requires LibreOffice in PATH; the CLI fails fast with an install hint when missing. Default off — v0.2.x mammoth/python-pptx flatten-to-text path stays unchanged.

### Deferred for v0.4+

Rough edges intentionally NOT fixed in v0.3.0:

- **Multi-hop graph traversal** (`depth > 1`) — `GraphBackend.traverse` raises `NotImplementedError`. Forward + reverse at depth=1 are wired; multi-hop is still pending.
- **File watcher for indices** — semantic + graph rebuild manually via `rufino enable-embeddings` or `mcp-server --rebuild`. No auto-rebuild on note edit.
- **Output adapter consumption of semantic queries** — `_LexicalQueryAdapter` is lexical-only; output adapters that want semantic results must call `rufino query --mode semantic` from an external trigger and template the output over the result.
- **Parallel consolidator enrichment** for large corpora (>200 concepts). See `docs/superpowers/specs/2026-05-20-consolidator-enrichment-parallel.md`.
- **Hard-fail (retry) on compression below floor** instead of just warning — v0.3 emits a warning only; v0.4 may re-prompt the worker.

## Versioning + migrations

`upgrade.sh` is keyed on `rufino version`, which reads `src/rufino/version.py:VERSION`. **Code changes without a version bump are invisible to `upgrade.sh`** — it'll print `Already at X. Nothing to do.` after `git pull`. Bump `VERSION` *and* `pyproject.toml`'s `version` together when releasing.

Migrations are bash scripts in `migrations/`, named `<from>-to-<to>.sh`. They:
- run **in lexicographic order** (so name them in semver order)
- must be **idempotent** (`upgrade.sh` may re-run after a partial failure)
- run **against the new code** (the pipx reinstall happens before migrations) — they can't import the old API; read state files directly off disk or convert lazily on next normal run
- get tracked one-per-line in `~/.rufino/applied-migrations`
- have `$RUFINO_HOME` available

The directory contains markers for prior version transitions (`0.0.2-to-0.0.3.sh`, `0.0.3-to-0.1.0.sh`, `0.1.0-to-0.2.0.sh`). New migrations should follow the contract in `migrations/README.md`.

## Test conventions

- `tests/conftest.py` provides `tmp_vault` and `tmp_rufino_home` fixtures — use them rather than rolling your own tmp setup.
- Test files mirror the module structure (`test_ingest_*`, `test_process_*`, `test_qa_*`, `test_wizard_*`, etc.).
- `tests/integration/` exists for cross-engine tests; unit tests live flat under `tests/`.
- Many tests assert on `TransactionLog` rollback behavior — when you add a new disk-touching op, add a test that forces failure and verifies the rollback runs cleanly.

## Things to know before editing

- **The CLI is a façade.** `src/rufino/cli.py` should stay thin — actual orchestration belongs in the engine module's dispatcher/runner. If you find yourself adding branching logic in `cli.py`, push it down.
- **`emit_augmented`, `transform_hook`, `--mode full`, and the OllamaEmbedder are wired as of v0.2.0.** Embeddings are opt-in per vault (`rufino enable-embeddings`). Multi-hop graph traversal (`depth > 1`) and file-watcher reindexing remain deferred.
- **Adapter manifests are the API contract** between the wizard and the engine. Changing a manifest schema means updating the parser + validator + every adapter the wizard generates + the docs in `docs/primitives/`.
- **Pipx + uv backend gotcha** documented in `install.sh` step 3: `pipx install --force` fails on the uv backend when the venv already exists. The installer checks `pipx list --short` and uses `reinstall` when present, `install -e` when absent. Preserve this pattern if you touch the installers.
- **The wizard runs Claude.** `rufino bootstrap` shells out to the `claude` CLI with a system prompt and a restricted `--allowedTools` set. If you need to test the prompt without launching Claude, use `--dry-run`.
