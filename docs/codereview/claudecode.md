# Code Review — Rufino v0.2.0

**Reviewer:** Claude Code (Opus 4.7)
**Date:** 2026-05-19
**Branch:** `feat/v0.2.0`
**Range:** `5504732` (base) → `f2c7598` (HEAD)
**Scope:** 7 commits, ~4,400 LOC net, 55 files
**Method:** 4 parallel specialist reviewers (pr-review-toolkit:code-reviewer), one per phase cluster; cross-verified all Critical findings against the source before publishing.

---

## TL;DR

**Verdict — Conditionally ship.** The architecture is sound, the transaction-log discipline is real, and test coverage on the happy paths is strong (~1,800 LOC of new tests). However, **three Critical defects break documented contracts on day-one usage**, and one of v0.2.0's two flagship features (bounded worker I/O) is implemented but never invoked. None of the Criticals require redesign; all are 1–10 line fixes. Recommended sequence: fix the 3 Criticals + 4–5 highest-impact Importants, ship as v0.2.1.

**Top risks**

1. The default MCP tool `find_note` defaults to `mode="hybrid"` and crashes on every freshly-materialized vault (embeddings off by default) — the canonical "open the box and use it" path fails.
2. Cron uninstall uses substring matching on the marker; uninstalling adapter `drive` silently deletes adapter `drive-secondary`'s schedule.
3. The wizard materializes `emit_facts` Ingest manifests in a shape the engine parser rejects — `rufino ingest` against a wizard-generated adapter raises `AttributeError`.
4. Bounded worker I/O (1 MB cap, "promised" in v0.2.0) is implemented in `run_claude_worker` but no production code path calls it — every dispatcher still uses the blocking `run_claude` which buffers full stdout into parent memory before truncating.

**What's solid**

- `runtime/vault_lock.py` is a 38-line `fcntl.flock` wrapper that does what it says, with non-blocking fast-fail and clean context-manager cleanup.
- `runtime/transform_hook.py` + `engine/_transform_hook_invoker.py` is a small, well-typed contract with subprocess-timeout, stdout cap, path-traversal defense (`resolve().is_relative_to(adapter_root)`), and per-note isolation that's pinned by tests.
- The `TransactionLog` discipline holds — every Critical-class disk mutation in `runtime/scheduler/launchd.py` and `cli.py` either uses it or registers an inverse, with the exception of `install-ingest` (see Important findings).
- Worker IDs widened from `:03d` → `:04d` cleanly; no `:03d` survivors anywhere in source or tests.
- The release-cut commit ships a small, idempotent, Python-API-free migration script (`migrations/0.1.0-to-0.2.0.sh`) that meets the contract in `migrations/README.md`.

---

## All Critical findings (3)

These should block a clean v0.2.0 → v0.2.1 release.

### C1. `find_note` MCP tool default crashes on every default-config vault

`src/rufino/mcp_server/tools.py:13`

```python
def find_note(ql: QueryLayer, *, query: str) -> str | None:
    results = ql.search(query, mode="hybrid", k=1)
```

`mode="hybrid"` is hard-coded. The schema for `find_note` exposes no `mode` parameter to the MCP client. On a freshly-materialized vault (embeddings off by default per CLAUDE.md), `QueryLayer.search` routes to `engine/query/api.py:43-47` → `NotImplementedError` → `server.py:90-96` re-raises as `ValueError`. **Result:** the canonical "first thing Claude Code does in a new vault" tool call fails.

**Fix:** change `find_note` default to `mode="lexical"`, OR fall back to lexical when the resolved embedder is `NoopEmbedder`, OR detect `enabled=false` at QueryLayer-construction time and route hybrid → lexical with a single-line debug log.

### C2. Cron uninstall removes unrelated entries via substring match

`src/rufino/runtime/scheduler/cron.py:88-93`

```python
def _filter_other_entries(content: str, *, job_id: str) -> str:
    marker = f"{_MARKER_PREFIX}{job_id}"
    ...
    if marker not in line:
```

`if marker not in line` is a substring test. Uninstalling `job_id="rufino-ingest-vault-a"` will also delete the entry for `rufino-ingest-vault-abc` because the former's marker is a substring of the latter's line. Realistic collision pattern: adapters `drive` / `drive-secondary`, or vaults `notes` / `notes-old`.

**Impact:** silent loss of a working schedule for an unrelated adapter — the exact failure mode the marker design was meant to prevent.

**Fix:** compare exact tokens. The line ends with `# rufino-job:<id>`; use `line.rstrip("\n").endswith(f"# rufino-job:{job_id}")`, or `line.rstrip().rsplit(_MARKER_PREFIX, 1)[-1].strip() == job_id`.

Same class of issue lives in `list_jobs` at `cron.py:57-60` (uses `line.find(_MARKER_PREFIX)` — first occurrence — so a command body containing the literal `# rufino-job:` reports a garbage job_id). Lower severity, same root cause.

### C3. Wizard-materialized `emit_facts` Ingest manifest is invalid

`src/rufino/wizard/spec_schema.py:192` + `src/rufino/wizard/adapter_materializers/ingest.py:86-87` + `src/rufino/engine/ingest/manifest.py:73-74`

The wizard validates and stores `destination` as a **string** (`_require_str` on `spec_schema.py:192`), and the materializer writes it back as a plain string. The engine parser at `manifest.py:73-74` calls `dest.get("facts")` / `dest.get("raw")`, expecting a **mapping**.

```python
# spec_schema.py:192
kwargs["destination"] = _require_str(entry, "destination", where=where)

# adapter_materializers/ingest.py:86-87
if spec.destination is not None:
    d["destination"] = spec.destination

# engine/ingest/manifest.py:73-74
destination_facts=dest.get("facts"),
destination_raw=dest.get("raw"),
```

**Impact:** every wizard-materialized Ingest adapter using `output_mode: emit_facts` will fail `parse_ingest_manifest` the moment `rufino ingest` runs against it. This blocks the big-bang materialization → first-run flow.

**Fix:** require `destination` as a mapping with `facts`/`raw` keys in `spec_schema.py`, OR teach `manifest.py` to accept both shapes. Add a regression test that runs a real `emit_facts` `RufinoSpec` through `materialize` → `parse_ingest_manifest`.

Closely related issue (Important): no wizard-side tests load a materialized manifest and run a primitive against it. `tests/integration/test_v0_2_end_to_end.py:336-343` hand-rolls the manifests instead of going through the materializer, which is exactly why C3 slipped through.

---

## High-impact Important findings (cross-phase)

These don't block, but they break promises CLAUDE.md / docs make.

### I-A. Bounded worker I/O is dead code

`src/rufino/engine/process/batch/runner_helper.py:57-108` (defines `run_claude_worker`) vs `runner_helper.py:143` (`run_claude`).

Verified: every production caller still invokes `run_claude` (blocking, full-buffer-then-truncate):

```
dispatcher.py:77      result: ClaudeResult = await run_claude(...)
consolidator.py:105   result = await run_claude(...)
retry.py:84           result = await run_claude(...)
qa_resume.py:229      result = await run_claude(...)
```

The streaming, bounded, early-stop `run_claude_worker` has zero production callers. CLAUDE.md advertises "Bounded I/O — worker stdout/stderr capped at `MAX_OUTPUT_BYTES` (1MB)" as a v0.2.0 deliverable, and `docs/primitives/process.md:174` repeats the claim. As shipped, **a runaway worker can still OOM the parent process**; `run_claude` only truncates *after* the bytes have already been buffered (lines 138-139). Additionally, `WorkerResult.truncated` (line 34) is never plumbed to a user-visible warning, so users have no signal when output was clipped.

**Fix:** wire `run_claude_worker` into `dispatcher._run_one` (and the three other callers), or have `run_claude` delegate to it under the hood with a backward-compatible signature. Surface `truncated` in the run summary.

### I-B. Wizard never emits `fetcher.py`

`src/rufino/wizard/adapter_materializers/ingest.py` writes `manifest.yaml` only. The engine ingest runner needs an importable `fetcher.py` for any external source. `tests/integration/test_v0_2_end_to_end.py:336-343` and `:379-383` hand-write a `fetcher.py` to make `run_ingest` succeed.

**Impact:** a wizard-materialized Ingest adapter is **non-functional out of the box** — the user runs `rufino ingest <adapter_dir>` and gets a `ModuleNotFoundError` (or equivalent), undermining the "open the box and it works" big-bang promise.

**Fix:** either capture a `fetcher_body` field in `IngestSpec` and write it as `fetcher.py`, OR materialize a TODO scaffold with a clear top-of-file marker so users know what's left to fill in. Pick one and document it.

### I-C. `transform_hook` is unreachable from the wizard

`src/rufino/wizard/spec_schema.py:29-48` — no field for `transform_hook`. The system prompt at `system_prompt_assembler.py:25` mentions "transform.py opcional (sandbox)" only in passing. The materializer never copies a `transform.py` nor adds `transform_hook:` to the manifest.

**Impact:** CLAUDE.md sells `transform_hook` as a v0.2.0 deliverable, and the runtime works correctly (Phase 0+3 Strength), but the only way to use it is hand-editing the materialized manifest. The wizard is blind to it.

**Fix:** add an optional `transform_hook` field to `IngestSpec`/`ProcessSpec`, teach the materializer to copy a wizard-supplied `transform.py` body, and document the capture pattern in `system_prompt_assembler.py`'s rules.

### I-D. No `TransactionLog` for `install-ingest`

`src/rufino/cli.py:565-602` writes logs dir, plist file, and mutates launchd/crontab state without any `apply_and_log` wrapper. The `plist_uninstall` rollback handler exists and is registered in `runtime/transaction_log.py:64-70`, but `install_ingest_cmd` doesn't use it.

**Impact:** a `^C` between steps or an unexpected `OSError` mid-install leaves the system in inconsistent state with no recovery record. Violates the project's documented "all disk-touching ops go through the tx log" invariant.

**Fix:** build a `TransactionLog` at `~/.rufino/tx/install-ingest-<job_id>.json`, record `mkdir`/`plist_install` ops, rollback on exception.

### I-E. `LaunchdBackend.install` loses the prior working schedule on a re-install failure

`src/rufino/runtime/scheduler/launchd.py:43-58`

The sequence is: overwrite plist in place → `bootout` old → `bootstrap` new. If `bootstrap` fails, the inline rollback unlinks the new plist — but the old service is **already booted out**. The user goes from "old schedule running" to "no schedule running" on a failed update.

**Fix:** write the new plist to a temp filename, `bootout` the old, `bootstrap` the new, `os.replace` to the canonical name only on success. Or stash the old plist content for restore.

### I-F. `enable-embeddings` writes vault state outside the TransactionLog

`src/rufino/cli.py` enable/disable handlers call `write_vault_state` directly. If `rebuild_indices()` half-succeeds (some embeddings written to `_meta/embeddings.sqlite`) and then Ollama drops, the user is left with a partial sqlite index but `embeddings.enabled=false` — re-running `enable-embeddings` silently appends/duplicates.

**Fix:** register `vault_state_write` / `embedding_index_rebuild` rollback handlers; run via `apply_and_log`.

### I-G. Cross-encoder model unpinned + silent multi-hundred-MB download

`src/rufino/runtime/embedder/cross_encoder.py:12` uses `"BAAI/bge-reranker-base"` via `sentence_transformers.CrossEncoder(...)` with no `revision=` lock, no documented model name, no offline gate. First `--mode=hybrid` query silently downloads ~400 MB to `~/.cache/huggingface/`, blocking for minutes on a slow connection. Hub compromise / typosquat could ship a malicious model.

**Fix:** pin a `revision=` (commit SHA), document the model+size in `docs/cli-reference.md`, prefetch in `enable-embeddings` so the cost is paid up-front.

### I-H. Cross-encoder error-handling catches only `ImportError`

`src/rufino/engine/query/api.py:71` catches `ImportError` to fall back to union order. The more common failure (HuggingFace network failure during model download, disk full, corrupted cache) raises `OSError`/`RuntimeError` and surfaces as an opaque crash.

**Fix:** broaden the except to `(ImportError, OSError, RuntimeError)`, or wrap `CrossEncoder.__init__` with explicit error mapping.

---

## Phase-by-phase findings

Each phase reviewer returned its own structured report. The Critical entries below are the same ones consolidated above (C1–C3); they're repeated here in context so the section reads independently. Importants and Minors are phase-specific.

### Phase 0+3 — Foundation + Worker Primitives

**Commits:** `bde49ac` (vault_lock, bounded I/O, worker padding, spec schema) + `6129145` (transform_hook, emit_augmented, mode=full)

#### Critical (0)

None — the primitives are correct in their intended behavior.

#### Important (5)

- **I-A. Bounded I/O implemented but never invoked in production** — see cross-phase section above.
- **`truncated` flag is silent.** Even if `run_claude_worker` were used, `WorkerResult.truncated` (runner_helper.py:34) is never surfaced. Surface in run summary + per-worker warning.
- **`emit_augmented` blocks on a single permanently-bad record.** `src/rufino/engine/ingest/emit_augmented.py:97-99` — cursor advances only on a fully clean batch. No dedup store (unlike `_run_emit_fact` which uses `DedupStore`). Every poll re-fetches the same record, fails, quarantines under `staging/failed/<id>.md` (which already exists → `rename` raises on Linux), cursor stays put → permanent stall. **Fix:** add a dedup store for emit_augmented or advance cursor best-effort with quarantined records logged.
- **`emit_augmented` silently ignores `process_inline_with`.** `engine/ingest/emit_augmented.py:66-71` — manifest requires the field, runner logs `INFO` that it's "parsed but ignored in v0.2". User who carefully points at `process_inline_with: my-tagger` gets generic light processor with no `WARNING` or validation error. **Fix:** downgrade field to optional + `WARNING` on use, or honor the field and exit 2 if unsupported.
- **`dispatch_to_process` collides on missing `id`.** `emit_augmented.py:35` — `note_path = staging_dir / f"{record.get('id', 'unknown')}.md"`. Two records without ids both target `unknown.md`; second `write_text` overwrites first silently. **Fix:** synthesize a deterministic id from content hash, or fail the batch explicitly.

#### Minor (6)

- `_process_light` not atomic; `emit_augmented` failure mid-stream leaves vault half-mutated (`engine/process/dispatcher.py:79-92`).
- `emit_augmented.run_emit_augmented` does not acquire the vault advisory lock — concurrent `process-batch` interleaves writes to `_tags.md` and `_processing-log.md` (`engine/ingest/emit_augmented.py:51-106`).
- `failed/` rename collides on retry — `note_path.rename(failed / note_path.name)` raises FileExistsError when same record fails twice.
- `MAX_OUTPUT_BYTES` is a hardcoded module constant with no validation or env-var override (`runner_helper.py:18`).
- Wizard/engine vocabulary drift: wizard uses `emit_facts` (plural), engine uses `emit_fact` (singular); translation at `wizard/adapter_materializers/ingest.py:13` works but is a footgun.
- "`staging preserved`" message in `cli.py:159` is misleading — the tempdir staging is gone; only the in-vault run_dir remains.

#### Strengths

- `runtime/transform_hook.py` — small, well-commented contract: stdin-JSON, stdout-JSON, single typed error for all failure modes; `default=str` defends against `datetime.date` from PyYAML; regression test pins it.
- Path-traversal defense in `_transform_hook_invoker.py:45` uses `.resolve().is_relative_to(adapter_root)` — symlink-safe and absolute-path-safe.
- `vault_lock.py` — 38 lines of `fcntl.flock` with `LOCK_NB` fast-fail; context-manager cleanup releases on `^C` / SIGTERM.
- `_apply_process_transform_hooks` uses per-note try/except (line 124) — `test_process_hook_continues_after_one_note_fails` proves the isolation.
- Worker IDs widened to `:04d` cleanly; no `:03d` survivors anywhere.

#### Test coverage assessment

Strong on documented graceful-degrade contracts: ~30 tests across transform_hook (success, timeout, non-zero exit, malformed JSON, path traversal, date coercion, per-note isolation) and process_single_full (CLI exit codes 0/1/3/127). Notable holes: no test asserts `truncated` is surfaced; no test for `dispatch_to_process` id collision; no test for `emit_augmented` ↔ `process-batch` lock interaction; no test that `process_inline_with` ignore behavior produces a warning.

---

### Phase 2+4 — Embedder + Graph Traversal

**Commits:** `4752adf` (Ollama + cross-encoder hybrid) + `2fd9d9e` (forward graph depth=1)

#### Critical (1)

- **C1. `find_note` MCP tool defaults to `mode="hybrid"` and crashes on default vaults** — see cross-phase section.

#### Important (7)

- **I-F. `enable-embeddings` writes vault state outside the TransactionLog** — see cross-phase.
- **I-G. Cross-encoder model unpinned + silent multi-hundred-MB download** — see cross-phase.
- **I-H. Cross-encoder error-handling catches only `ImportError`** — see cross-phase.
- **`SemanticBackend` materializes `_meta/embeddings.sqlite` even when embedder is `NoopEmbedder`.** `engine/query/semantic.py:__post_init__` unconditionally creates the dir and opens sqlite. Every vault that runs `rufino query` ends up with a phantom embeddings db. **Fix:** lazy-init or skip construction when embedder is `NoopEmbedder`.
- **`SemanticBackend.rebuild_index` lacks progress output.** A partial Ollama failure mid-corpus means the user waits 10 minutes, gets an exception, and has zero observability into how far it got. **Fix:** `click.echo` every N notes; document expected wall time.
- **Hybrid rerank tie-breaking is non-deterministic with identical content.** `engine/query/api.py:82-88` — `by_content` keyed by full file content; two notes with identical content (boilerplate/empty stubs) collapse to one entry. Add a test for two notes with identical content + a test for one note that raises OSError on read.
- **`enable-embeddings` requires `--state-dir`, but `query` / `mcp-server` / `output` default it.** A user who runs `enable-embeddings --state-dir /tmp/foo`, then later `query --mode hybrid` (no `--state-dir`), silently hits the default `~/.rufino/state`, finds no per-vault yaml, gets `NoopEmbedder`, and exits 2 with the wrong message. **Fix:** default `--state-dir` in enable/disable to `~/.rufino/state` too.

#### Minor (6)

- `OllamaDetection.model_installed` uses `startswith(model)` — false positives on prefix-matching models (`nomic-embed-text-v2` matches `nomic-embed-text`). Tighten to `m == model or m.startswith(f"{model}:")`.
- `detect_ollama` swallows network exceptions with bare `except Exception` (`detect.py:31`); narrow to `httpx.RequestError`.
- `GraphBackend` does not normalize wikilink targets (`engine/query/graph.py:48`) — `[[ML-I]]` vs `[[ml-i]]` create separate triples; anchors not stripped. Document or normalize.
- `docs/primitives/query.md:55` references `engine/query/backends/semantic.py` — wrong path (actual: `engine/query/semantic.py`).
- `docs/primitives/query.md:54` claims embeddings persist with `sqlite-vec`; actual impl stores `json.dumps(vec)` in TEXT and brute-forces cosine.
- `CrossEncoderReranker` is reinstantiated per hybrid query (`engine/query/api.py:58`) — lazy `_load_model` cache is thrown away each call. Memoize at module level or cache on `QueryLayer`.

#### Strengths

- `OllamaEmbedder` is intentionally thin and propagates errors loudly — no silent zero-vector swallowing.
- `resolve_embedder` cleanly separates the three states (missing yaml / enabled=false / enabled=true) and raises loudly on unknown backends.
- `write_vault_state` uses `tempfile.mkstemp` + `os.replace` for atomic writes — exactly right.
- `enable-embeddings` correctly orders `detect → rebuild → write state`, so mid-rebuild failure leaves the state file untouched. `test_enable_embeddings_does_not_write_state_when_rebuild_fails` pins this.
- Graph traversal commit is small, surgical, well-tested: forward, reverse, depth=1 vs 2, empty result, system-dir exclusion, non-string coercion all covered.

#### Test coverage assessment

50+ targeted assertions across Ollama, cross-encoder, detect, resolve, enable/disable, hybrid rerank, graph. Gaps: no hybrid mode on *empty* corpus or identical-content collisions; no integration test running `enable-embeddings` then `query --mode=hybrid` end-to-end through CLI (closest is `test_query_hybrid_with_rerank.py` which patches QueryLayer); no Unicode/whitespace-only queries; no test that `find_note` works on a vault with embeddings disabled (would catch C1 immediately).

---

### Phase 5 — Scheduler + Install Commands

**Commit:** `e88c87e` (launchd/cron + install-ingest)

#### Critical (1)

- **C2. Cron uninstall removes any entry whose marker is a prefix of the target job_id** — see cross-phase.

#### Important (5)

- **I-D. No `TransactionLog` for `install-ingest`** — see cross-phase.
- **I-E. `LaunchdBackend.install` loses the prior working schedule on re-install failure** — see cross-phase.
- **`install-ingest` interpolates user paths without resolving.** `cli.py:588-592` — `adapter_dir` and `vault_root` flow as `str(...)`. If the user passes `./adapter --vault ./vault`, the relative paths are baked into the scheduled command, which runs from the cron/launchd CWD (typically `/` or `$HOME`). **Fix:** `.expanduser().resolve(strict=True)` for both paths before composing.
- **`manifest.adapter_name` not validated against launchd Label / FS constraints.** `engine/ingest/manifest.py:14-22` accepts any string. Spaces, `/`, leading `.`, or unicode produce broken plist filenames or launchctl errors. `render.py:6` validates `^[A-Za-z0-9._-]+$` for `ScheduledJob`, but the new `SchedulerBackend.install()` path doesn't enforce it. **Fix:** validate `adapter_name` (and computed `job_id`) against the same regex.
- **`docs/runtime.md` scheduler section is stale.** Lines 139-173 still describe `install_job(job, tx_log=tx_log)` and `ScheduledJob(..., working_dir, stdout_log, stderr_log)` — none of which exist in the v0.2.0 API (`SchedulerBackend.install(*, job_id, schedule, cmd, log_path)`). Rewrite.

#### Minor (5)

- `list_jobs` uses `line.find` rather than the trailing marker; a command containing `# rufino-job:` reports garbage job_id (`cron.py:56-61`).
- `launchctl bootout` errors silently absorbed in `uninstall()` (`launchd.py:49,62`). Surface unexpected exit codes.
- No test covers the prefix-collision scenario; closest test omits the case.
- `migrations/0.1.0-to-0.2.0.sh` doesn't acknowledge scheduler state (technically correct — v0.1.0 had none — but worth a comment).
- `_rufino_invocation()` prefers `which rufino` over `sys.executable -m rufino`; the latter is more stable across cron's reduced env (`cli.py:48-53`).

#### Strengths

- `validate_cron` is shared between `LaunchdBackend.install` and `CronBackend.install` — single source of truth.
- Cron entry built with `shlex.quote(log_path)` and newline rejection on `cmd`/`job_id` — basic shell-injection hygiene present.
- Plist XML escaping via `xml.sax.saxutils.escape` applied to all interpolated user values; `test_scheduler_launchd.py:146-153` pins it.
- `LaunchdBackend.install` is idempotent via `bootout`-before-`bootstrap`; test pins the order.
- CLI tests inject the backend via `monkeypatch` on `_scheduler_backend` — clean OS-independent seam.

#### Test coverage assessment

Backend-level coverage is strong on happy paths (install/uninstall/list, plist XML, calendar vs interval mapping, XML escaping) and one classic failure (bootstrap fails → plist removed). Missing: (1) prefix-collision on `_filter_other_entries` — the Critical above; (2) `install-ingest` end-to-end with a relative path; (3) re-install while a prior plist is loaded (lost-on-failure path); (4) `adapter_name` with shell-unsafe chars.

---

### Phase 1+6 — Wizard + Release Artifacts

**Commits:** `9d335e4` (wizard end-to-end) + `f2c7598` (release v0.2.0)

#### Critical (1)

- **C3. Wizard `emit_facts` Ingest produces an invalid manifest (`destination` shape mismatch)** — see cross-phase.

#### Important (5)

- **I-B. Wizard never materializes `fetcher.py`** — see cross-phase.
- **I-C. Wizard cannot generate `transform_hook` adapters** — see cross-phase.
- **`dedup_by` type mismatch wizard↔engine.** Wizard collects `dedup_by` as `list[str]` (`spec_schema.py:193-196`), engine expects `str | None` (`engine/ingest/manifest.py:25`). Parsing won't raise (no type check), but downstream consumers expecting a scalar break unpredictably. **Fix:** align on list-of-strings; update engine manifest dataclass.
- **`MaterializationResult` swallows underlying exception type.** `wizard/materializer.py:187-201` — bare `except Exception` flattens every failure into a single error string. Disk full / invalid manifest / keychain failure all read the same. **Fix:** distinct excepts per error class, or log traceback to a state-dir error file.
- **Doc drift: `claude -p` references in three places.** `docs/cli-reference.md:17,29` shows `(ej: 0.1.0)` and `claude -p`; `CLAUDE.md:30` and `CLAUDE.md:62` repeat `claude -p`. Actual implementation at `cli.py:407-427` uses interactive `claude --system-prompt ... --allowedTools ... -- "<kickoff>"` and explicitly comments that `-p` is wrong.

#### Minor (5)

- `CLAUDE.md:33` still says `# full is stubbed (exits 2)` — wrong as of `6129145`.
- No `CHANGELOG.md`; the 12-gap closure lives only in `CLAUDE.md` and `docs/upgrading.md`.
- Wizard passes the whole `system_prompt` on argv (`cli.py:407-425`). Today ~5-8 KB — safe; if `patterns/` grows, will exceed argv limits on some BSDs.
- `render_user_readme` shows users `rufino query "tu pregunta" --vault {spec.vertical_name}` — `--vault` takes a *path*, not a vertical name. Generated README tells users a broken command (`post_bootstrap_docs.py:43`).
- System prompt `_TEMPLATE` mixes singular/plural output_modes (`system_prompt_assembler.py:24`) — `emit_fact` vs wizard-side `emit_facts`. Translated at the boundary but a footgun.

#### Strengths

- Materializer composes its three sub-materializers under a shared `TransactionLog`; `tests/test_materialize_full_spec.py:104-135` proves leaves are removed after a forced `install_memory_loop` failure.
- `spec_schema.py` deep-freezes nested dicts via `MappingProxyType`; regex-anchored entity/adapter name validation; tests at `test_wizard_spec_schema.py:104-115,126-139` are strong.
- `0.1.0-to-0.2.0.sh` — short, no Python-API imports, idempotency guards (`mkdir -p`, `[ ! -f ... ]`), round-trip tested at `test_item_13_migration_writes_vault_state_idempotently`.
- `test_v0_2_end_to_end.py` (589 lines) exercises the actual CLI via `CliRunner`; mocks only external IO (Ollama detect, scheduler backend, `run_batch`).
- Per-vault MCP server name `ask-rufino-<slug>` + `--state-dir` propagation in `cli.py:482-499` correctly avoids multi-vault clobbering.

#### Test coverage assessment

Wizard materializer is well-covered structurally — round-trip YAML, layout, rollback, "all primitives" tests all exist. The gap is functional coverage of the *content*: no test loads a wizard-materialized Ingest manifest and runs `rufino ingest` end-to-end, which is why C3 and I-B slipped through. `test_v0_2_end_to_end.py` is the right venue, but item #7 hand-rolls a `fetcher.py` instead of going through the materializer.

#### Documentation accuracy assessment

`docs/cli-reference.md` and `docs/upgrading.md` are accurate for new flags. Drift is concentrated in three "small but visible" places: the `claude -p` references (CLAUDE.md ×2, cli-reference.md ×1), the stubbed-`--mode full` claim in CLAUDE.md:33, and the `--vault <vertical_name>` example in the generated README. `docs/upgrading.md:178-191` is a faithful summary of the migration and the new commands.

---

## Recommended fix order

1. **C1** (find_note default) — 1-line change in `mcp_server/tools.py`; add a test asserting `find_note` works on an embeddings-off vault.
2. **C3** (wizard emit_facts shape) — spec_schema + materializer + a regression test that runs the materializer output through `parse_ingest_manifest`.
3. **C2** (cron prefix collision) — 1-line change in `cron.py:_filter_other_entries`; add prefix-collision unit test.
4. **I-A** (bounded I/O dead code) — wire `run_claude_worker` into `dispatcher._run_one` and the three other callers; surface `truncated` in the run summary.
5. **I-B** (wizard fetcher.py) + **I-C** (wizard transform_hook) — decide v0.2.1 vs v0.3.0; if v0.3.0, document the gap clearly in `docs/upgrading.md`.
6. **I-D** + **I-E** (install-ingest tx log + plist safety) — both touch scheduler install path; bundle in one commit.
7. **I-F** + **I-G** + **I-H** (embedder hardening) — bundle.
8. **Doc cleanup** — `claude -p` references, CLAUDE.md:33 stubbed-claim, `docs/runtime.md` stale section, `docs/primitives/query.md` paths and sqlite-vec claim.
9. **Minor / Strengths-preserving cleanup** — as bandwidth allows.

---

## Numbers

- **Files reviewed:** 55 source + tests + docs (see `git diff --stat 5504732..f2c7598`).
- **Findings:** 3 Critical, 22 Important, 22 Minor, ~22 Strengths.
- **Tests in scope:** ~1,800 LOC new tests across 15 new test files + integration test (589 LOC).
- **Critical defects verified against source:** 3 of 3.

---

*Generated by 4 parallel `pr-review-toolkit:code-reviewer` agents, each scoped to one phase cluster. Critical findings independently re-verified against `HEAD` source before publication.*
