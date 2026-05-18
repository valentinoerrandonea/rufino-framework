# Process batch via Claude orchestration — design

**Status:** draft 2026-05-18 — pending Val's review
**Author:** Val + Claude
**Tracking:** unblocks end-to-end processing of a raw corpus into an augmented vault. Target release: v0.1.0.

## Problem

`rufino bootstrap` already materializes the vault, the MCP server, the adapters and the memory-loop hooks, but it does **not** process raw content. The Process primitive has its `--mode full` stubbed (`cli.py:88` exits with code 2), and Ingest's `import_raw` drops docs into the inbox without anything triggering augmentation. A user who arrives with a corpus (e.g. a ZIP of Google Docs exported from Drive, 12 subjects, ~hundreds of docs) has the vault scaffolding but no way to convert that material into augmented notes.

The original plan documented in `docs/primitives/process.md` was to wire a real LLM client inside Rufino (Anthropic SDK + API key in keychain) and finish `process --mode full`. That plan is replaced by this design.

## Approach: Rufino orchestrates Claude Code, does not embed an LLM

The augmentation work — read the raw note, query the vault for related concepts, write the augmented version, update indices — is exactly what Claude Code does today when the user works interactively. Rather than re-implement that loop inside Rufino against the Anthropic SDK, this design has Rufino **spawn `claude` headless** as worker subprocesses, with the Process adapter's prompt as the system prompt, the `ask-rufino-<slug>` MCP server for context, and the vault as the destination.

Consequences:

- No Anthropic SDK dependency. No API key handling.
- No need to wire Ollama urgently — the worker uses the vault's lexical query via the MCP, which already works.
- The user's existing `claude` CLI session (Pro/Max or otherwise) is the auth surface.
- Each worker is a real Claude Code session — multimodal (sees diagrams in PDFs), uses tools (Read, Write, Glob, MCP), can open Q&As.

`process --mode full` (the single-note CLI command) stays stubbed in this release. Single-note augmentation is achievable by running `process-batch` against a one-file directory; reviving the single-note command can come later as a thin wrapper if ergonomics demand it.

## Design

### 1. CLI

```bash
rufino process-batch <zip-or-dir> \
  --adapter <process-adapter-dir> \
  --vault <vault-root> \
  [--workers N]       # default: min(4, num_groups)
  [--batch-size N]    # default: read from the adapter manifest
  [--dry-run]         # stop after PLAN, print plan.json, do not spawn workers
```

`<zip-or-dir>` accepts a ZIP file or an already-extracted directory. Stays accepting both because users hand both forms naturally.

The single-note `rufino process --mode full` command remains stubbed (exits 2 with current message). Reviving it is **out of scope** for this release.

### 2. Six-stage flow

```
STAGE  →  PLAN  →  DISPATCH  →  VALIDATE+RETRY  →  CONSOLIDATE  →  COMMIT
 (R)      (R)        (R+W)          (R)               (W)           (R+T)
```

`R` = Rufino, `W` = Claude worker(s), `T` = transaction log.

`--dry-run` cuts after PLAN.

#### 2.1 STAGE (Rufino)

- If input is a ZIP, extract to a temp dir. Fix filename encoding: try utf-8 first, fall back to cp437→utf-8 reinterpretation (typical of Windows-created ZIPs from Drive export).
- For each file:
  - `.md`, `.txt`, `.pdf` → copy verbatim into `<vault>/.rufino/runs/<run-id>/inbox/<group>/<slug>.<ext>`. PDFs stay PDFs because Claude Code's Read tool handles them multimodally (preserves diagrams, formulas, scans).
  - `.docx` → convert to markdown via `mammoth`, write `.md`.
  - `.pptx` → convert to markdown via `python-pptx` (one section per slide), write `.md`.
  - `.doc`, `.ppt` (legacy) → log a warning, skip. (Requires `pandoc` / LibreOffice; out of scope.)
  - Any other extension → log a warning, skip.
- `<group>` is derived from the top-level folder of each file in the corpus (one materia = one group in the facultad case). Files at the root of the corpus go to `<group>=_root`.

Output: a `StagedCorpus(groups: dict[str, list[Path]])`.

#### 2.2 PLAN (Rufino)

Adaptive batching by simple rules:

- For each group, if `len(group) ≤ batch_size` → one worker handles the full group.
- Else → split into ceil(len/batch_size) consecutive chunks, one worker per chunk.

`batch_size` defaults to the Process adapter's manifest field (new field, see §3), falls back to 10 if absent. CLI `--batch-size` overrides.

`--workers` caps concurrent worker subprocesses. Default `min(4, total_workers)`.

Output: a `Plan` object, serialized to `<run-dir>/plan.json`:

```json
{
  "run_id": "2026-05-18T22-15-32Z",
  "adapter_dir": "/abs/path/.rufino/adapters/process/apunte-clase",
  "workers": [
    {
      "worker_id": "w001",
      "group": "algoritmos-ii",
      "notes": ["inbox/algoritmos-ii/clase-01.md", "inbox/algoritmos-ii/clase-02.md"]
    },
    ...
  ]
}
```

#### 2.3 DISPATCH (Rufino spawns Claude workers)

For each worker assignment, Rufino spawns:

```python
subprocess.run([
    "claude",
    "-p",
    "--system-prompt", <built-prompt>,
    "--allowedTools",
        "Read,"
        "Write,"
        "Glob,"
        f"mcp__ask-rufino-{slug}__*",
    "--cwd", <staging-dir-of-worker>,
    "--",
    "Procesá las notas listadas en assignment.json siguiendo el system prompt.",
])
```

`--cwd` is the worker's staging dir so any Write call is implicitly contained. The vault canon is never touched at this stage.

Worker staging dir: `<vault>/.rufino/runs/<run-id>/workers/<worker-id>/`.

Workers run in parallel under an asyncio semaphore bounded by `--workers`.

#### 2.4 Worker system prompt — three concatenated blocks

**Block 1 — Operative preamble (written by Rufino):**

- Role: "Sos un worker de Rufino procesando notas en batch."
- List of assigned notes (absolute paths to `inbox/<group>/<slug>.<ext>`).
- Staging dir path where output goes.
- I/O contract: for each note, produce `augmented/<slug>.md` and `deltas/<slug>.json` in the staging dir (see §2.5).
- How to trigger a Q&A: end the output with a recognizable block (see §2.7).

**Block 2 — Adapter prompt (`<adapter-dir>/prompt.md`):**

- Triple vocabulary.
- Output schema (required + optional frontmatter fields with types).
- Tag axes (orthogonal tag categories with min/max).
- Vertical-specific augmentation instructions, generated by the wizard.

**Block 3 — Vault context (written by Rufino):**

- "Tenés acceso al MCP `ask-rufino-<slug>`. Usalo para buscar conceptos existentes, evitar duplicados, detectar wikilinks."
- A top-N (default 30) list of concept slugs currently in `<vault>/conceptos/`, to bias the worker toward reusing rather than reinventing.

#### 2.5 Worker I/O contract — exact output expected

Per assigned note, two files in the staging dir:

**`augmented/<slug>.md`** — the augmented note. YAML frontmatter (matching the adapter's `output_schema` and `triple_vocabulary`) + markdown body:

```markdown
---
title: ...
note_type: apunte_clase
created: 2026-05-12
tags: [materia/algoritmos, tema/grafos, profesor/lopez]
triples:
  - { s: "DFS", r: "tema-de", o: "Algoritmos II" }
wikilinks: ["[[BFS]]", "[[Algoritmos II]]"]
source: <input-path-relative-to-vault>
---

# Augmented body of the note
...
```

**`deltas/<slug>.json`** — the same updates, explicit, for the consolidator's benefit:

```json
{
  "note_slug": "2026-05-12-grafos",
  "tags_added": ["materia/algoritmos", "tema/grafos"],
  "triples_emitted": [{"s": "DFS", "r": "tema-de", "o": "Algoritmos II"}],
  "concepts_referenced": ["DFS", "BFS", "Algoritmos II"],
  "concepts_promoted": ["DFS"],
  "wikilinks_added": ["[[BFS]]", "[[Algoritmos II]]"],
  "qa_opened": [],
  "warnings": []
}
```

`deltas/<slug>.json` duplicates information available in the frontmatter. The duplication is intentional: it makes consolidation cheaper (read N JSONs vs parse N markdowns) and survives mildly malformed frontmatter.

#### 2.6 VALIDATE + RETRY (Rufino)

After all workers finish, for each `(augmented.md, delta.json)`:

- Parse frontmatter with `parse_frontmatter`. Failure → flag for retry.
- Validate frontmatter against `manifest.output_schema` (required fields, types). Failure → flag for retry.
- Extract triples, validate against `manifest.triple_vocabulary`. Failure → flag for retry.
- Parse `delta.json`. Failure → flag for retry.

For each flagged note, Rufino spawns a single-note retry worker with the same system prompt **plus** an appended block:

```
═══ RETRY ═══

Procesaste esta nota antes y el output no pasó validación. Los errores:

- <specific error 1>
- <specific error 2>

El input original sigue siendo el mismo. Rehacelo corrigiendo esos puntos.
```

Max 2 retries per note (configurable, default 2). After max retries fail, the note moves to `<run-dir>/workers/<wid>/failed/<slug>/` containing the last `augmented.md`, `delta.json` (if parseable), and an `error.json` with the validation errors. The run continues with the remaining notes.

#### 2.7 Q&A blocks

If the adapter's manifest declares `qa_triggers` and the worker decides one fires (e.g. ambiguous `materia`), the worker writes ONLY one file in its staging dir for that note: `pending/<slug>.json`, instead of the regular `augmented/<slug>.md` + `deltas/<slug>.json`. Format:

```json
{
  "origin": "process-batch",
  "run_id": "<run-id>",
  "worker_id": "<worker-id>",
  "pending_note": "<slug>",
  "input_path": "inbox/<group>/<slug>.<ext>",
  "trigger": "<qa_trigger-name>",
  "context": "<short text the worker can use to resume after the answer>",
  "question": "<question-text>"
}
```

The `origin: "process-batch"` field is what the `qa-poll` resumption handler dispatches on (see §9).

Rufino, after VALIDATE, scans worker staging dirs for `pending/*.json`. For each one: writes a Q&A note to `<vault>/questions/<id>.md` (reusing existing engine machinery), records the pending entry in `run.json`, and leaves the note out of both the OK queue and `failed/`. The COMMIT for that note is deferred until the user answers and `qa-poll` resumes it. Other notes in the same run commit normally.

**Wiring `qa-poll` resumption (which is stubbed today at `cli.py:154-194`) is part of this release.**

#### 2.8 CONSOLIDATE (Claude consolidator)

After VALIDATE+RETRY, Rufino spawns a single `claude -p` consolidator with a different system prompt:

- Read all `workers/*/deltas/*.json` and `workers/*/augmented/*.md`.
- Read existing `<vault>/_meta/_tags.md`, `<vault>/_meta/_index.md`, `<vault>/conceptos/`.
- Detect duplicate concepts emitted independently across workers (e.g. two workers from different materias both wrote `conceptos/DFS.md` with slightly different content).
- Produce `<run-dir>/consolidation-plan.json`:

```json
{
  "moves": [
    {"from": "workers/w001/augmented/clase-01.md", "to": "apuntes/algoritmos-ii/2026-05-12-grafos.md"}
  ],
  "concept_writes": [
    {"path": "conceptos/dfs.md", "content": "...", "wins_over": ["workers/w001/concept-dfs.md", "workers/w003/concept-dfs.md"]}
  ],
  "tag_index_updates": [
    {"tag": "materia/algoritmos", "notes": ["2026-05-12-grafos", "2026-05-19-arboles"]}
  ],
  "log_entries": [
    "batch-processed run=<id> notes=N ok=N failed=N"
  ]
}
```

Consolidator runs with allowedTools `Read,Glob,mcp__ask-rufino-<slug>__*` — no Write. Its only output is the plan JSON, written to a specific staging path.

If the consolidator times out (default: 10 min) or returns an empty plan, Rufino falls back to a naive commit: each `augmented.md` moves to the destination from its frontmatter, indices are appended with each delta's contributions, no cross-grupo concept dedup. The vault ends up consistent but with possible concept duplication that the user can clean up.

If the consolidator returns a plan that fails schema validation, the run aborts with exit 1, vault untouched, staging preserved.

#### 2.9 COMMIT (Rufino, via transaction log)

Rufino opens a transaction log at `<vault>/.rufino/runs/<run-id>/commit.tx.json` and applies the consolidation plan:

- For each move → `apply_and_log(tx_log, op="move", apply_fn=..., rollback=move-back)`.
- For each concept write → `apply_and_log(tx_log, op="write", apply_fn=..., rollback=delete-or-restore)`.
- For each tag index update → `apply_and_log(tx_log, op="append-tag-index", apply_fn=..., rollback=remove-line)`.
- Append log entries.

If any step fails, `tx_log.rollback()` runs the inverses in reverse order, and the vault is left exactly as it was pre-commit. Staging dir is preserved for inspection.

If all steps succeed, the staging dir's `inbox/`, `workers/*/augmented/`, `workers/*/deltas/`, `consolidation-plan.json`, and `commit.tx.json` are kept. `failed/` is kept regardless. The `run-id` directory is never auto-deleted — the user manages cleanup.

### 3. Adapter manifest change

`src/rufino/engine/process/manifest.py` gains one optional field:

```yaml
batch_size: <int>      # default: 10. Workers handle up to this many notes per spawn.
```

Validator: must be a positive integer ≥ 1. If absent, default 10.

### 4. Module layout

New `src/rufino/engine/process/batch/`:

| Module | Responsibility |
|---|---|
| `converters.py` | `docx_to_md(path)`, `pptx_to_md(path)`. Pure functions, raise `UnsupportedFormatError` for `.doc`/`.ppt`. |
| `stager.py` | `stage_corpus(source, run_dir)` — unzip + encoding fix + per-format dispatch. Returns `StagedCorpus`. |
| `planner.py` | `build_plan(staged, batch_size, max_workers)` → `Plan`. Serializes to `plan.json`. |
| `dispatcher.py` | `dispatch(plan, adapter, run_dir, vault_root, max_workers)` — async parallel spawn of `claude -p` workers. |
| `worker_prompt.py` | `build_worker_system_prompt(adapter, assignment, vault_root, staging_dir)` — three-block prompt assembly. |
| `validator.py` | `validate_worker_output(staging_dir, manifest)` → `ValidationReport`. Reuses existing `validate_against_schema`, `validate_triples_against_vocab`. |
| `retry.py` | `retry_failed(failed, adapter, max_retries=2)` — re-invoke worker with augmented prompt. |
| `consolidator.py` | `run_consolidator(run_dir, vault_root, adapter)` — spawn one `claude -p`, returns parsed `consolidation_plan`. |
| `committer.py` | `commit(plan, vault_root, tx_log)` — apply via transaction log. |
| `runner.py` | `run_batch(source, adapter_dir, vault_root, workers, batch_size, dry_run)` — top-level orchestrator. |

`src/rufino/cli.py` gains a `process_batch_cmd` (~40 lines) calling `runner.run_batch`.

New deps in `pyproject.toml`: `mammoth>=1.6`, `python-pptx>=0.6`.

### 5. Concurrency & isolation

- Workers each get their own staging dir; the vault canon is read-only during STAGE→VALIDATE→CONSOLIDATE.
- Only COMMIT writes to the vault canon, and it does so single-threaded inside the Rufino process under a transaction log.
- Two concurrent `process-batch` runs against the same vault: out of scope. The CLI takes an advisory lock at `<vault>/.rufino/process-batch.lock`; if held, refuses to start with a clear message.

### 6. Authentication

Workers use the existing `claude` CLI session of the user. No API key handling. Same assumption as `rufino bootstrap`: `claude` is in PATH and logged in. Sessions that have expired surface as worker exit codes that Rufino translates to an aborting error ("Tu sesión Claude está expirada, corré `claude login`").

This release explicitly does **not** support unattended (cron, launchd) operation. v1.2+ may add an API-key fallback if the user wants that.

### 7. Error handling

Principle: the vault canon is untouched until COMMIT. Everything before commits to `<vault>/.rufino/runs/<run-id>/`. If commit fails, transaction log rolls back.

| Stage | Error | Handling |
|---|---|---|
| STAGE | Corrupt ZIP | Exit 1, vault untouched. |
| STAGE | Unrecoverable filename encoding | Warn, skip file, run continues. |
| STAGE | Unsupported format (`.doc`, `.ppt`, unknown) | Warn, skip. |
| STAGE | Conversion error (mammoth/python-pptx) | Warn, skip, log path + error. |
| PLAN | Empty corpus | Exit 1. |
| PLAN | Invalid `batch_size` | Exit 1 (defensive — validator should have caught earlier). |
| DISPATCH | `claude` not in PATH | Exit 127 with message. |
| DISPATCH | Worker crash / timeout | Notes assigned to that worker → retry path. After max retries → `failed/`. |
| DISPATCH | `claude` reports expired session | Exit 1 with specific message; run aborts. |
| VALIDATE | Any validation failure | → retry path. |
| CONSOLIDATE | Timeout / empty plan | Fallback to naive commit (no cross-grupo dedup). |
| CONSOLIDATE | Plan fails schema | Exit 1, staging preserved. |
| COMMIT | Any failure | `tx_log.rollback()`, exit 2 (rare). |

Exit codes:
- `0` — run committed (may include notes in `failed/`).
- `1` — run aborted before commit.
- `2` — commit failed mid-way, rollback applied.
- `127` — `claude` not found.

### 8. Testing

Following repo conventions (`pytest`, `tmp_vault` / `tmp_rufino_home` fixtures, `tests/` flat for units, `tests/integration/` for cross-engine).

Unit tests, one per new module:

| Test file | Covers |
|---|---|
| `test_batch_converters.py` | `docx_to_md` fixture input → expected md; `pptx_to_md` idem; `.doc`/`.ppt` raise `UnsupportedFormatError`. |
| `test_batch_stager.py` | ZIP unzip + cp437 encoding fix (fixture with `clase-álgebra.md` misencoded); skip unsupported; PDF passthrough verbatim. |
| `test_batch_planner.py` | Single materia → 1 worker; > batch_size → N workers; manifest `batch_size` respected; CLI `--batch-size` override; `--dry-run` cuts here. |
| `test_batch_dispatcher.py` | Stubbed `claude` (bash script writing canon outputs to staging); parallelism bounded by `--workers`; timeout triggers as expected; expired-session stub aborts run. |
| `test_batch_validator.py` | Bad frontmatter, triple out of vocab, missing required field, malformed `delta.json` each flag; clean output passes. |
| `test_batch_retry.py` | Fail once → retry; fail twice → `failed/`; augmented prompt contains specific error text. |
| `test_batch_consolidator.py` | Stubbed consolidator; empty plan → fallback; invalid plan → run aborts. |
| `test_batch_committer.py` | Commit OK → files at destination + indices updated; commit failure mid-way → `tx_log.rollback()`; staging preserved. |

Integration test `tests/integration/test_batch_end_to_end.py`:

Corpus fixture with 5 notes (2 `.md`, 1 `.docx`, 1 `.pdf`, 1 `.pptx`) across 2 groups. Stubbed `claude` executes a Python script that, per note, reads the input, emits canned augmentation, and writes `augmented/` + `deltas/`. Verifies:

- 5 notes land at their `<destination_path>` rendered targets.
- `_meta/_tags.md` has expected tags, no duplicates.
- `consolidation-plan.json` produced and applied.
- `run.json` reports `total=5, ok=5, failed=0`.

Stubbed `claude` lives at `tests/fixtures/fake_claude/claude` — a Python executable (shebang `#!/usr/bin/env python3`) that mimics the real `claude -p` calling convention closely enough to exercise the dispatcher and consolidator paths without spending tokens. The test fixtures point `PATH` at this dir for the duration of the test.

Coverage target: 85%+ on `engine/process/batch/`, 80%+ overall.

Manual-only test `tests/manual/test_batch_with_real_claude.py` exists for the contract surface (system prompt + tool grants) and is run before releases that change `worker_prompt.py`. Not in CI.

### 9. Q&A loop wiring (in scope)

`cli.py:qa_poll_cmd` currently raises `_ResumptionNotImplemented` and exits 2 when answers are detected. This release replaces that handler with a real one:

- On a poll, for each answered question whose Q&A originated from a `process-batch` run, the handler re-spawns a single-note worker for the pending note with the answer injected into the prompt's RETRY-style appended block.
- The worker's output goes through VALIDATE+RETRY+COMMIT just like a fresh note (a mini-COMMIT scoped to that note's destination + index deltas, under a fresh transaction log).
- After commit, the answered question file is archived (moved to `<vault>/questions/answered/<id>.md`).

Q&As that did not originate from `process-batch` (e.g. wizard-time questions) keep their existing behavior — the handler dispatches by `adapter_state.origin`.

### 10. Versioning

Bump `VERSION` (and `pyproject.toml` `version`) to `0.1.0` — minor bump, first feature release after the post-bootstrap fix sprint.

Migration `migrations/0.0.3-to-0.1.0.sh`:

- Updates `~/.rufino/applied-migrations` (the standard migration tracking).
- Does NOT touch user vaults. Migrations under `migrations/` operate on `~/.rufino/` only, per the existing contract; vault paths are not enumerated there.
- Vault-side adjustment (adding `.rufino/runs/` to the vault's `.gitignore` if one exists) is handled lazily on the first `process-batch` run against a given vault. The runner checks for `<vault>/.gitignore`, appends the line if missing, and proceeds. Idempotent.

No state file format changes; the new feature is additive.

## Out of scope

- **Reviving `rufino process --mode full`**: stays stubbed. Single-note processing via `process-batch` against a one-file directory.
- **Real embedder (Ollama) / semantic context injection at worker time**: workers get lexical context via the MCP. Semantic adds value but is independent work.
- **`emit_augmented` ingest dispatcher inline path**: still deferred; this release does not touch Ingest.
- **`transform_hook` runner**: still deferred.
- **Unattended (cron) operation**: requires API key fallback, out of scope.
- **`.doc` / `.ppt` legacy support**: requires pandoc / LibreOffice, out of scope.
- **PDF passthrough beyond what Read tool supports natively**: very large PDFs (>20 pages per chunk) may need pagination logic; not handled in this release.
- **Concurrent `process-batch` against the same vault**: prevented by advisory lock; multi-run scheduling is out of scope.
- **Vault watcher / continuous ingest of a folder**: separate feature, would land as an Ingest adapter shape (`watched-folder`), independent of this design.

## Open items resolved during brainstorming

| Question | Decision |
|---|---|
| Embed an LLM client vs orchestrate Claude? | Orchestrate Claude. |
| Single invocation vs per-note vs hybrid? | Hybrid: Rufino plans, Claude workers process, Claude consolidator merges. |
| Worker granularity? | Adaptive: 1 group = 1 worker unless > batch_size; default batch_size = 10. |
| CLI entry shape? | New dedicated command `rufino process-batch`. |
| Isolation strategy? | Staging dirs + final consolidation via transaction log. |
| Validation failure handling? | Retry max 2 with augmented prompt, then bouncing to `failed/`. |
| Authentication? | User's `claude` CLI session (no API key in v0.1.0). |
| Input formats? | `.md`/`.txt`/`.pdf` passthrough, `.docx`/`.pptx` converted, `.doc`/`.ppt` skipped. |
| Revive `process --mode full`? | No; stays stubbed. |

## Test plan

- All unit tests above pass (`pytest tests/test_batch_*.py`).
- Integration end-to-end test passes (`pytest tests/integration/test_batch_end_to_end.py`).
- Manual smoke against real `claude` with a tiny corpus (3 md files, 1 PDF, 1 docx) — verifies system-prompt contract and tool grants on the actual binary.
- `pytest --cov=src/rufino/engine/process/batch` reports ≥ 85% on the new modules.
- Existing test suite still passes (no regressions in single-note Process, Ingest, Output, Query, MCP, wizard).
- `rufino process-batch --dry-run <corpus> --adapter X --vault Y` prints a plausible `plan.json` without spawning workers.
- `rufino process-batch` with a known-bad adapter manifest fails fast at PLAN with a clear message.
- A run interrupted between DISPATCH and COMMIT leaves the vault untouched; the staging dir is inspectable and the user can rerun.
