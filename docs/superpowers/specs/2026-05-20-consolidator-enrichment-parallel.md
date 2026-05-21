# Consolidator enrichment — parallel pass for large corpora

**Status:** v0.4 candidate
**Discovered in:** v0.3 (Gap 1+2 implementation, 2026-05-20)

## Problem

The v0.3 consolidator preamble asks for enriched concept bodies + author
bios in a single `claude` headless invocation. For small corpora (<200
concepts) this works. For large corpora — the facultad vault has 597
concepts across 108 apuntes — the consolidator times out before
finishing.

Observed in the wizard session of 2026-05-20: Val had to follow up with a
manual pass dispatching 5 parallel subagents, each enriching ~120
concepts, because the single-shot consolidator wall-clock exceeded the
600s default `timeout_seconds` in `run_consolidator(...)`.

## Proposal

Split the consolidator into two phases:

1. **Plan phase** (current `run_consolidator`): dedup, emit `moves` +
   `tag_index_updates` + stubs of `concept_writes` / `author_writes` with
   only `path` populated (no `content`) plus `wins_over` so dedup
   information is preserved.

2. **Enrich phase** (new): a parallel pool of `claude` headless workers,
   pool size = `min(5, ceil(N / 100))` where N is `len(concept_writes) +
   len(author_writes)`. Each worker takes a chunk of slugs and produces
   the enriched bodies, writing back to a per-worker partial plan. The
   final consolidation plan is the merged union.

The worker count + chunking heuristic should mirror the existing
`process-batch` `WorkerAssignment` shape so it reuses the dispatcher
infrastructure (`src/rufino/engine/process/batch/dispatcher.py`).

## Acceptance

- For a corpus with ≥ 200 concepts, consolidation completes within the
  same total wall-time as today (or better — parallelism amortizes the
  cost across CPUs available to the `claude` CLI).
- No regression for small corpora — the enrich phase is a no-op when
  N < 50 (plan phase emits full content directly, as today).
- Plan schema remains backward compatible: enriched bodies still live in
  the same `concept_writes[].content` / `author_writes[].content`
  fields. The plan JSON format does not change.
- `run_consolidator` retains its v0.3 signature; the parallel path is
  reachable via a new `run_consolidator_parallel(...)` helper or via a
  `parallel: bool` kwarg with default False.

## Open questions for the v0.4 brainstorm

- Where does the per-worker partial plan live? A new `enrich/` subdir
  inside `run_dir`, or one JSON per slug under `{run_dir}/enrich/`?
- How do we surface partial enrichment failures? Plan phase succeeded
  but one enrich worker timed out — do we ship the plan with stub
  bodies for the failed chunk, or fail the whole batch?
- The `_naive_commit_plan` fallback today fires only when the
  consolidator returns None. In the two-phase model, what is the
  fallback granularity — plan-phase-failed vs enrich-phase-partial?
