# Codex Code Review: process-batch plan implementation

Scope reviewed:
- `docs/superpowers/plans/2026-05-18-process-batch-via-claude-orchestration.md`
- `docs/superpowers/plans/2026-05-18-process-batch-phases.md`
- Current implementation under `src/rufino/engine/process/batch/`, `src/rufino/cli.py`, docs, and tests.

## Findings

### C1. `qa-poll` archives answered process-batch questions without committing the resumed note

`docs/primitives/process.md:52-57` says the commit for a Q&A note is deferred until the user answers and runs `rufino qa-poll`. The implementation in `src/rufino/engine/process/batch/qa_resume.py:147-166` only validates the regenerated `augmented/<slug>.md` and `deltas/<slug>.json`, then moves the question to `questions/answered/`. It never runs consolidation, the naive commit planner, or `commit()`.

Impact: a user can answer a batch question, see `dispatched=1`, and lose the only visible pending indicator while the note remains stranded in `.rufino/runs/.../workers/.../augmented/` instead of landing in the vault canon.

Reproduction performed:
- Ran `rufino qa-poll` against a synthetic answered process-batch question with fake Claude in `augment` mode.
- Result: `dispatched=1`, question archived, `staged_aug=True`, but `committed_notes=[]`.

Recommended fix:
- After a successful validation in `resume_pending_qa`, apply the resumed note to the vault via the same commit path used by `run_batch`.
- At minimum, build a one-note `ConsolidationPlan` from the manifest `destination_path` and call `commit()`.
- Add a regression test that asserts the resumed note exists outside `.rufino/` after `qa-poll`, not only that the question was archived.

### C2. Missing, empty, timed-out, or nonzero worker outputs can disappear from accounting and retry

`dispatch()` returns `WorkerOutcome` for non-session failures, and its docstring says nonzero exits and empty outputs are left for validation (`src/rufino/engine/process/batch/dispatcher.py:99-103`). But `run_batch()` ignores the dispatch result entirely (`src/rufino/engine/process/batch/runner.py:219-244`), and `validate_worker_output()` only iterates files that exist under `augmented/` (`src/rufino/engine/process/batch/validator.py:97-115`). If there is no `augmented/` directory, validation returns an empty report.

Impact: a planned note can produce no output and still end with `notes_failed=0`, no retry, no `failed/<slug>/` marker, and no Q&A. This breaks the plan's VALIDATE+RETRY guarantee and makes run summaries untrustworthy.

Reproduction performed with `FAKE_CLAUDE_MODE=empty`:

```text
{'notes_total': 1, 'notes_ok': 0, 'notes_failed': 0, 'pending_qa': 0}
```

Recommended fix:
- Make validation assignment-aware: for every note in each `WorkerAssignment`, require exactly one terminal state: valid augmented+delta, pending Q&A, or failed.
- Feed nonzero/timeout `WorkerOutcome` into validation or synthesize `NoteValidation` failures for every note assigned to that worker.
- Add tests for `FAKE_CLAUDE_MODE=empty`, `fail`, and `hang` at the `run_batch()` level and assert `notes_failed == notes_total` or pending Q&A as appropriate.

### C3. Commit rollback loses pre-existing vault files overwritten by batch moves

The plan requires final COMMIT through `TransactionLog` so failures roll back cleanly. `commit()` snapshots concept writes and index/log changes, but plain note moves do not snapshot an existing destination. The move path is `shutil.move(src, dest)` at `src/rufino/engine/process/batch/committer.py:102-118`; rollback only moves the current destination back to the staging source (`src/rufino/engine/process/batch/committer.py:44-50`).

Impact: if `apuntes/n1.md` already exists and a batch move targets the same path, the existing canonical note is overwritten. If a later operation fails and rollback runs, rollback moves the new note back to staging and deletes the destination, permanently losing the old canonical note. This violates the atomic commit guarantee and can destroy user vault content.

Reproduction performed:
- Created existing `vault/apuntes/n1.md` with `OLD`.
- Committed a plan whose first move writes `NEW` to the same destination and whose second move fails.
- After rollback: destination no longer existed; staging source was restored with `NEW`; `OLD` was gone.

Recommended fix:
- For `plan.moves`, snapshot existing destinations before moving, just like concept overwrites.
- Rollback should restore the previous destination if it existed, or delete the new destination if it did not.
- Also reject duplicate `to` paths within one plan before applying any operations.
- Add tests for overwriting an existing note followed by a later failure, and for duplicate move destinations.

### H1. Staging flattens nested paths within a group and silently overwrites duplicate filenames

The stager groups by top-level directory (`src/rufino/engine/process/batch/stager.py:64-67`), but `_stage_one_file()` writes every passthrough file as `inbox/<group>/<src_file.name>` and every converted file as `inbox/<group>/<src_file.stem>.md` (`src/rufino/engine/process/batch/stager.py:70-86`). That discards subdirectory context.

Impact: a normal corpus like `math/unit1/lesson.md` and `math/unit2/lesson.md` stages two plan entries pointing at the same `inbox/math/lesson.md`; the second copy overwrites the first. The run claims two notes, but both worker inputs refer to the same file content. Converted files can collide with each other or with markdown files by stem as well.

Reproduction performed:

```text
group_count 2
paths ['inbox/math/same.md', 'inbox/math/same.md']
unique_paths 1
final_text TWO
```

Recommended fix:
- Preserve the path relative to the group root under `inbox/<group>/...`, or generate deterministic unique staged names while storing original source metadata.
- Add collision detection and fail fast if two source files map to the same staged path.
- Add tests for duplicate basenames in nested folders and for converted `.docx` colliding with `.md` by stem.

## Verification

Targeted tests run:

```bash
pytest tests/test_batch_runner.py tests/test_batch_committer.py \
  tests/test_cli_qa_poll_resumption.py tests/integration/test_batch_end_to_end.py -q
```

Result: 14 passed, 1 failed. The failure was `tests/integration/test_batch_end_to_end.py::test_full_pipeline_end_to_end` because the current local environment lacks `mammoth`:

```text
ModuleNotFoundError: No module named 'mammoth'
```

`pyproject.toml` declares `mammoth>=1.6` and `python-pptx>=0.6`, so this is likely an environment/setup issue rather than a source issue. It still means I could not verify the mixed-format integration test in this workspace without installing project dependencies.

Additional focused reproductions were run for C1, C2, C3, and H1 as described above.
