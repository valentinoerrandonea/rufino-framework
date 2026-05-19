# process-batch Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix every finding from the two comprehensive code reviews of `rufino process-batch` (v0.1.0) — Claude review at `docs/codereview/review-claude.md` and Codex review at `docs/codereview/codex.md`. Three of the issues are silent-data-loss bugs in the commit / dispatch / stager paths; two more are path-traversal and missing-commit defects in qa-resume; the rest cover Q&A hardening, environment robustness, documentation gaps, and test-infrastructure cleanup.

**Architecture:** Single linear plan — every fix lives inside the `process-batch` subsystem (`src/rufino/engine/process/batch/`, the CLI, tests, and docs). Tasks are ordered by blast radius (data-loss bugs first, then security, then UX, then test hygiene). Each task follows TDD: failing test → minimal fix → passing test → commit.

**Tech Stack:** Python 3.12, pytest, dataclasses, asyncio, pathlib, click. Test harness uses a `fake_claude` subprocess fixture under `tests/fixtures/fake_claude/`.

---

## Findings consolidados (origen)

| Task | Severity | Source | Short title |
|---|---|---|---|
| T1 | 🔴 Critical | Codex C3 + Claude H7 | Commit rollback loses pre-existing vault files; NUL round-trip untested |
| T2 | 🔴 Critical | Codex C2 (escala Claude M17) | Empty/timeout/nonzero worker outputs disappear from accounting |
| T3 | 🔴 Critical | Codex H1 | Stager flattens nested paths and silently overwrites duplicate filenames |
| T4 | 🔴 Critical | Codex C1 + Claude C1, C2, H4 | qa-resume never commits; path traversal via question YAML; FAKE_CLAUDE_NOTES env var leak |
| T5 | 🟠 High | Claude H1, H2, M1, M2, M6 | Q&A pipeline aborts on bad slug; crashes on corrupt YAML; non-atomic writes; non-string guard |
| T6 | 🔴 Critical | Claude C3 | mammoth/python-pptx import at module load → 9 tests crash on clean install |
| T7 | 🔴 Critical | Claude C4, C5, H9 | `docs/cli-reference.md` lacks process-batch section; stale v0.0.2; `batch_size` undocumented |
| T8 | 🟡 Medium | Claude H10, M15 | Consolidator happy path untested; dispatcher cancellation untested |
| T9 | 🟠 High | Claude H8 | E2E test scope narrower than commit title (no ZIP, no CLI, no negative path) |
| T10 | 🟡 Medium | Claude M13, M14 | CWD-dependent fixture paths; duplicated `FAKE_DIR` + `_make_adapter` helpers |
| T11 | 🟢 Low | Claude M3-M11, nits | Cleanup sweep: hardcoded strings, mutable dataclass, magic numbers, etc. |

Skipped (deferred to v0.2 or later):
- **Claude H3** (unbounded stdout/stderr capture in `run_claude`) — documented as v0.1 acceptable in the original plan. Add a TODO comment instead.
- **Advisory lock per vault** (design §9) — explicitly out-of-scope per the spec.
- **Claude M16** (worker_id `:03d` width) — does not bite until >999 workers. Add to deferred list in CLAUDE.md.

---

## Task 1: Snapshot existing destinations + reject duplicate moves + NUL round-trip

**Why:** `commit()` calls `shutil.move(src, dest)` without snapshotting the destination first. If `dest` already exists, the old vault file is destroyed by `move`. Rollback then moves the new file back to staging and unlinks the destination — permanently losing the user's previous canonical note. Codex confirmed this with a repro: pre-existing `apuntes/n1.md` containing `OLD`, plan moves `NEW` to the same path then second move fails → `OLD` is gone after rollback.

Also: `LogEntry.target` uses `\x00` to encode multi-field state, but no test pins the JSON round-trip (`TransactionLog.load`) — a future refactor changing the separator silently passes all current tests and breaks rollback at runtime.

**Files:**
- Modify: `src/rufino/engine/process/batch/committer.py:102-118` (move with snapshot)
- Modify: `src/rufino/engine/process/batch/committer.py:92-100` (`commit` pre-check for duplicate `to` paths)
- Test: `tests/test_batch_committer.py` (3 new tests)

### Steps

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_batch_committer.py`:

```python
def test_commit_snapshots_existing_destination_and_rollback_restores_old_content(tmp_path):
    """C3 codex: pre-existing dest must survive rollback when later op fails."""
    vault = tmp_path / "vault"
    run_dir = tmp_path / "run"
    (vault / "apuntes").mkdir(parents=True)
    (vault / "apuntes" / "n1.md").write_text("OLD", encoding="utf-8")

    (run_dir / "workers" / "w001" / "augmented").mkdir(parents=True)
    (run_dir / "workers" / "w001" / "augmented" / "n1.md").write_text("NEW", encoding="utf-8")

    plan = ConsolidationPlan(
        moves=[
            {"from": "workers/w001/augmented/n1.md", "to": "apuntes/n1.md"},
            {"from": "workers/w001/augmented/missing.md", "to": "apuntes/missing.md"},
        ],
        concept_writes=[], tag_index_updates=[], log_entries=[],
    )
    tx = TransactionLog(run_dir / "tx.json")
    with pytest.raises(FileNotFoundError):
        commit(plan=plan, vault_root=vault, run_dir=run_dir, tx_log=tx)

    # After rollback the OLD content must be back at the destination
    assert (vault / "apuntes" / "n1.md").read_text(encoding="utf-8") == "OLD"


def test_commit_rejects_duplicate_destinations(tmp_path):
    """Two moves cannot target the same path within one plan."""
    vault = tmp_path / "vault"
    run_dir = tmp_path / "run"
    aug = run_dir / "workers" / "w001" / "augmented"
    aug.mkdir(parents=True)
    (aug / "a.md").write_text("A", encoding="utf-8")
    (aug / "b.md").write_text("B", encoding="utf-8")

    plan = ConsolidationPlan(
        moves=[
            {"from": "workers/w001/augmented/a.md", "to": "apuntes/x.md"},
            {"from": "workers/w001/augmented/b.md", "to": "apuntes/x.md"},
        ],
        concept_writes=[], tag_index_updates=[], log_entries=[],
    )
    tx = TransactionLog(run_dir / "tx.json")
    with pytest.raises(ValueError, match="duplicate destination"):
        commit(plan=plan, vault_root=vault, run_dir=run_dir, tx_log=tx)
    # Vault must be untouched
    assert not (vault / "apuntes" / "x.md").exists()


def test_committer_nul_encoded_target_survives_json_roundtrip(tmp_path):
    """H7: rollback after reload from disk must still parse \\x00-encoded target."""
    vault = tmp_path / "vault"
    run_dir = tmp_path / "run"
    (vault / "apuntes").mkdir(parents=True)
    (vault / "apuntes" / "n1.md").write_text("OLD", encoding="utf-8")
    aug = run_dir / "workers" / "w001" / "augmented"
    aug.mkdir(parents=True)
    (aug / "n1.md").write_text("NEW", encoding="utf-8")

    plan = ConsolidationPlan(
        moves=[{"from": "workers/w001/augmented/n1.md", "to": "apuntes/n1.md"}],
        concept_writes=[], tag_index_updates=[], log_entries=[],
    )
    tx_path = run_dir / "tx.json"
    tx = TransactionLog(tx_path)
    commit(plan=plan, vault_root=vault, run_dir=run_dir, tx_log=tx)

    # Reload tx_log from disk and rollback
    reloaded = TransactionLog.load(tx_path)
    reloaded.rollback()
    assert (vault / "apuntes" / "n1.md").read_text(encoding="utf-8") == "OLD"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_batch_committer.py::test_commit_snapshots_existing_destination_and_rollback_restores_old_content \
       tests/test_batch_committer.py::test_commit_rejects_duplicate_destinations \
       tests/test_batch_committer.py::test_committer_nul_encoded_target_survives_json_roundtrip -v
```

Expected: 3 FAIL. First fails because rollback loses OLD. Second fails because duplicate detection doesn't exist. Third may pass already if `TransactionLog.load` works — verify; if it does, that's fine, the test still pins the behaviour.

- [ ] **Step 3: Implement the fix**

In `src/rufino/engine/process/batch/committer.py`, replace the move-loop in `commit()` (lines 101-118) with:

```python
    # Reject duplicate destinations before any disk op.
    seen: set[str] = set()
    for m in plan.moves:
        if m["to"] in seen:
            raise ValueError(f"duplicate destination in plan: {m['to']!r}")
        seen.add(m["to"])

    try:
        for m in plan.moves:
            src = _safe_in_run_dir(run_dir, m["from"])
            dest = _safe_in_vault(vault_root, m["to"])
            if not src.exists():
                raise FileNotFoundError(f"missing source: {src}")
            dest.parent.mkdir(parents=True, exist_ok=True)

            if dest.exists():
                snap = _new_backup_path(run_dir, dest.stem)
                shutil.copy2(dest, snap)

                def _do_move(src=src, dest=dest) -> None:
                    shutil.move(str(src), str(dest))

                apply_and_log(
                    tx_log,
                    op="batch_move_overwrite",
                    target=f"{dest}{_NUL}{src}{_NUL}{snap}",
                    apply_fn=_do_move,
                    rollback="batch_undo_move_overwrite",
                )
            else:
                def _do_move(src=src, dest=dest) -> None:
                    shutil.move(str(src), str(dest))

                apply_and_log(
                    tx_log,
                    op="batch_move",
                    target=f"{dest}{_NUL}{src}",
                    apply_fn=_do_move,
                    rollback="batch_undo_move",
                )
```

Add a new rollback handler near `_undo_move`:

```python
def _undo_move_overwrite(target: str) -> None:
    """Restore dest from snap, then move dest back to src. Target format:
    ``"<dest>\\x00<src>\\x00<snap>"``."""
    parts = target.split(_NUL)
    if len(parts) != 3:
        return
    dest, src, snap = parts
    # First, move the new content back to staging (undo of the move)
    if Path(dest).exists() and Path(snap).exists():
        Path(src).parent.mkdir(parents=True, exist_ok=True)
        shutil.move(dest, src)
        shutil.copy2(snap, dest)
    elif Path(snap).exists():
        shutil.copy2(snap, dest)


register_rollback("batch_undo_move_overwrite", _undo_move_overwrite)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_batch_committer.py -v
```

Expected: all green (including pre-existing tests — verify nothing regresses).

- [ ] **Step 5: Commit**

```bash
git add src/rufino/engine/process/batch/committer.py tests/test_batch_committer.py
git commit -m "$(cat <<'EOF'
fix(batch): snapshot vault destinations before move + reject duplicate moves

Pre-existing vault files were silently destroyed when commit() called
shutil.move(src, dest) — rollback then lost the old content forever.
Now snapshots dest before move and registers batch_undo_move_overwrite
to restore the old file on failure. Also rejects plans with duplicate
"to" paths before touching disk. Pins the NUL-encoded target JSON
round-trip with a reload-from-disk test.

Fixes Codex C3, Claude H7.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Make validate_worker_output assignment-aware (no silent disappearance)

**Why:** Today `run_batch()` ignores the return value of `dispatch()` (`runner.py:219`) and `validate_worker_output()` only enumerates files under `augmented/`. A worker that produces nothing — `FAKE_CLAUDE_MODE=empty`, a timeout, a nonzero exit — leaves an empty `augmented/` directory, validation returns an empty report, and the run summary claims `notes_failed=0`. Codex confirmed this with `FAKE_CLAUDE_MODE=empty`: `{'notes_total': 1, 'notes_ok': 0, 'notes_failed': 0, 'pending_qa': 0}`. This breaks the plan's VALIDATE+RETRY guarantee.

**Approach:** Validator becomes assignment-aware — for every note in `WorkerAssignment.notes`, exactly one terminal state must exist: valid augmented+delta, valid pending Q&A, or a synthesized failure entry. The validator no longer assumes `augmented/` is the source of truth.

**Files:**
- Modify: `src/rufino/engine/process/batch/validator.py` (new `validate_worker_output` signature accepting an assignment)
- Modify: `src/rufino/engine/process/batch/runner.py:229-244` (pass assignment to validator)
- Test: `tests/test_batch_validator.py`, `tests/test_batch_runner.py`

### Steps

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_batch_runner.py`:

```python
@pytest.mark.asyncio
async def test_runner_empty_worker_output_counts_as_failure(tmp_path, monkeypatch):
    """Codex C2: FAKE_CLAUDE_MODE=empty must produce notes_failed == notes_total."""
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "empty")
    vault, adapter, source = _make_minimal_setup(tmp_path)  # helper: creates 1 .md, manifest

    result = await run_batch(
        source=source, adapter_dir=adapter, vault_root=vault,
        workers=1, batch_size=1, dry_run=False,
        skip_consolidator=True, timeout_seconds=10.0,
    )

    assert result.notes_total == 1
    assert result.notes_ok == 0
    assert result.notes_failed == 1


@pytest.mark.asyncio
async def test_runner_worker_timeout_counts_as_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "hang")
    vault, adapter, source = _make_minimal_setup(tmp_path)

    result = await run_batch(
        source=source, adapter_dir=adapter, vault_root=vault,
        workers=1, batch_size=1, dry_run=False,
        skip_consolidator=True, timeout_seconds=0.5,
    )

    assert result.notes_failed == 1
    assert result.notes_ok == 0


@pytest.mark.asyncio
async def test_runner_worker_nonzero_exit_counts_as_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "fail")
    vault, adapter, source = _make_minimal_setup(tmp_path)

    result = await run_batch(
        source=source, adapter_dir=adapter, vault_root=vault,
        workers=1, batch_size=1, dry_run=False,
        skip_consolidator=True, timeout_seconds=10.0,
    )

    assert result.notes_failed == 1
```

Append to `tests/test_batch_validator.py`:

```python
def test_validator_synthesizes_failure_for_missing_augmented(tmp_path, simple_manifest):
    """Every assignment note that produces neither augmented nor pending is a failure."""
    staging = tmp_path / "workers" / "w001"
    staging.mkdir(parents=True)
    # Worker wrote nothing — no augmented/, no pending/

    assignment = WorkerAssignment(
        worker_id="w001", group="root",
        notes=(tmp_path / "inbox" / "root" / "n1.md",),
    )
    report = validate_worker_output(staging, simple_manifest, assignment=assignment)

    assert len(report.failed) == 1
    assert report.failed[0].slug == "n1"
    assert any("no output" in e for e in report.failed[0].errors)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_batch_runner.py::test_runner_empty_worker_output_counts_as_failure \
       tests/test_batch_runner.py::test_runner_worker_timeout_counts_as_failure \
       tests/test_batch_runner.py::test_runner_worker_nonzero_exit_counts_as_failure \
       tests/test_batch_validator.py::test_validator_synthesizes_failure_for_missing_augmented -v
```

Expected: all 4 FAIL.

- [ ] **Step 3: Implement the fix**

In `src/rufino/engine/process/batch/validator.py`, change `validate_worker_output` signature and body:

```python
def validate_worker_output(
    staging_dir: Path,
    manifest: WorkerAdapterManifest,
    *,
    assignment: "WorkerAssignment | None" = None,
) -> ValidationReport:
    """Validate worker output. When ``assignment`` is provided, every note in
    the assignment must produce a terminal artifact (augmented+delta, pending,
    or synthesized failure). Without an assignment we fall back to the legacy
    "enumerate augmented/" behavior — kept for backward compat with tests that
    don't have an assignment in hand.
    """
    aug_dir = staging_dir / "augmented"
    pending_dir = staging_dir / "pending"
    delta_dir = staging_dir / "deltas"
    passed: list[NoteValidation] = []
    failed: list[NoteValidation] = []

    if assignment is None:
        if not aug_dir.exists():
            log.info("no augmented/ in %s; treating as pending-only or empty", staging_dir)
            return ValidationReport()
        for aug_path in sorted(aug_dir.glob("*.md")):
            delta_path = delta_dir / f"{aug_path.stem}.json"
            result = validate_one(aug_path, delta_path, manifest)
            (passed if result.passed else failed).append(result)
        return ValidationReport(passed=tuple(passed), failed=tuple(failed))

    for note_path in assignment.notes:
        slug = note_path.stem
        aug_path = aug_dir / f"{slug}.md"
        delta_path = delta_dir / f"{slug}.json"
        pending_path = pending_dir / f"{slug}.json"
        if aug_path.exists():
            result = validate_one(aug_path, delta_path, manifest)
            (passed if result.passed else failed).append(result)
        elif pending_path.exists():
            # Pending Q&A is a valid non-failure terminal state; do not list.
            continue
        else:
            failed.append(NoteValidation(
                slug=slug, augmented_path=aug_path, delta_path=None,
                errors=(f"worker produced no output for slug={slug!r}",),
            ))
    return ValidationReport(passed=tuple(passed), failed=tuple(failed))
```

Add to imports at top of file:

```python
from rufino.engine.process.batch.planner import WorkerAssignment  # for type hint
```

In `src/rufino/engine/process/batch/runner.py:231`, change:

```python
        report = validate_worker_output(staging_dir, manifest)
```

to:

```python
        report = validate_worker_output(staging_dir, manifest, assignment=assignment)
```

Add helper `_make_minimal_setup` in `tests/test_batch_runner.py` if not already present:

```python
def _make_minimal_setup(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    adapter = _make_adapter(tmp_path / "adapter")  # existing helper
    source = tmp_path / "corpus"
    source.mkdir()
    (source / "n1.md").write_text("# n1\n", encoding="utf-8")
    return vault, adapter, source
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_batch_runner.py tests/test_batch_validator.py -v
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add src/rufino/engine/process/batch/validator.py \
        src/rufino/engine/process/batch/runner.py \
        tests/test_batch_validator.py tests/test_batch_runner.py
git commit -m "$(cat <<'EOF'
fix(batch): validate assignment-aware, surface empty/timeout/nonzero worker failures

validate_worker_output() now iterates assignment.notes when given an
assignment, synthesizing a failure for any note that produced neither
augmented/ nor pending/. The runner threads the assignment through.
Previously a worker producing nothing left validation with an empty
report and notes_failed=0 — silent data loss.

Fixes Codex C2.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Preserve nested paths in stager + reject collisions

**Why:** `_stage_one_file` writes every file as `inbox/<group>/<src_file.name>`. A corpus like `math/unit1/lesson.md` + `math/unit2/lesson.md` ends up with two plan entries pointing at the same `inbox/math/lesson.md`; the second copy silently overwrites the first. Codex confirmed: `group_count=2, paths=['inbox/math/same.md', 'inbox/math/same.md'], unique_paths=1, final_text=TWO`.

**Files:**
- Modify: `src/rufino/engine/process/batch/stager.py:64-89` (preserve relpath under group)
- Test: `tests/test_batch_stager.py`

### Steps

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_batch_stager.py`:

```python
def test_stage_preserves_nested_subdirs_within_group(tmp_path):
    """Codex H1: math/unit1/lesson.md and math/unit2/lesson.md must not collide."""
    source = tmp_path / "corpus"
    (source / "math" / "unit1").mkdir(parents=True)
    (source / "math" / "unit2").mkdir(parents=True)
    (source / "math" / "unit1" / "lesson.md").write_text("ONE", encoding="utf-8")
    (source / "math" / "unit2" / "lesson.md").write_text("TWO", encoding="utf-8")
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    staged = stage_corpus(source, run_dir)

    math_paths = [p.relative_to(run_dir) for p in staged.groups["math"]]
    assert len(set(math_paths)) == 2, f"paths collided: {math_paths}"
    contents = {p.read_text(encoding="utf-8") for p in staged.groups["math"]}
    assert contents == {"ONE", "TWO"}


def test_stage_rejects_collision_after_extension_normalization(tmp_path):
    """A .docx that converts to lesson.md and a sibling lesson.md must not silently merge."""
    source = tmp_path / "corpus"
    source.mkdir()
    (source / "lesson.md").write_text("FROM_MD", encoding="utf-8")
    # Use the bundled fixture docx that converts to "lesson.md"
    fixture = Path(__file__).parent / "fixtures" / "batch" / "hello.docx"
    shutil.copy2(fixture, source / "lesson.docx")
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    with pytest.raises(StagingError, match="collision"):
        stage_corpus(source, run_dir)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_batch_stager.py::test_stage_preserves_nested_subdirs_within_group \
       tests/test_batch_stager.py::test_stage_rejects_collision_after_extension_normalization -v
```

Expected: both FAIL — first because paths collapse to `inbox/math/lesson.md` twice; second because no collision detection exists.

- [ ] **Step 3: Implement the fix**

In `src/rufino/engine/process/batch/stager.py`, change `_stage_one_file` to accept and use a relpath:

```python
def _stage_one_file(
    src_file: Path,
    inbox_group_dir: Path,
    rel_under_group: Path,
    skipped: list[Path],
) -> Path | None:
    suffix = src_file.suffix.lower()
    target_dir = inbox_group_dir / rel_under_group.parent
    target_dir.mkdir(parents=True, exist_ok=True)
    if suffix in PASSTHROUGH_EXTS:
        target = target_dir / src_file.name
        if target.exists():
            raise StagingError(f"staging collision at {target}")
        shutil.copy2(src_file, target)
        return target
    if suffix in CONVERTIBLE_EXTS:
        try:
            md = convert_to_markdown(src_file)
        except (ConversionError, UnsupportedFormatError) as e:
            log.warning("skipping %s: %s", src_file, e)
            skipped.append(src_file)
            return None
        target = target_dir / (src_file.stem + ".md")
        if target.exists():
            raise StagingError(f"staging collision at {target}")
        target.write_text(md, encoding="utf-8")
        return target
    log.warning("skipping unsupported format %s", src_file)
    skipped.append(src_file)
    return None
```

Change `stage_corpus` to pass the relpath:

```python
    for file in sorted(corpus_root.rglob("*")):
        if not file.is_file():
            continue
        rel = file.relative_to(corpus_root)
        if len(rel.parts) > 1:
            group = rel.parts[0]
            rel_under_group = Path(*rel.parts[1:])
        else:
            group = "_root"
            rel_under_group = rel
        inbox_group = inbox_root / group
        target = _stage_one_file(file, inbox_group, rel_under_group, staged.skipped)
        if target is not None:
            staged.groups.setdefault(group, []).append(target)
```

Remove the now-unused `_group_for` helper.

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_batch_stager.py -v
```

Expected: all green. Also run `pytest tests/test_batch_planner.py` since planner consumes the staged output — it should still pass because slugs come from `Path.stem`.

- [ ] **Step 5: Commit**

```bash
git add src/rufino/engine/process/batch/stager.py tests/test_batch_stager.py
git commit -m "$(cat <<'EOF'
fix(batch): preserve nested paths in stager + reject filename collisions

_stage_one_file now stages files under inbox/<group>/<relpath>/ rather
than collapsing every file to inbox/<group>/<basename>. A corpus like
math/unit1/lesson.md + math/unit2/lesson.md no longer silently merges
into one staged file. Also raises StagingError when a target path is
about to be overwritten — including the docx→.md vs .md collision case.

Fixes Codex H1.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: qa-resume commits via commit() + sanitizes question YAML + drops FAKE_CLAUDE_NOTES leak

**Why:** Three related defects in `qa_resume.py`:
1. After validation passes, the resumed augmented note is never committed to the vault canon — the function archives the question and returns true while the augmented file sits in `.rufino/runs/.../workers/.../augmented/` forever. Codex repro: `dispatched=1, staged_aug=True, committed_notes=[]`.
2. `run_id`, `worker_id`, `pending_note` are read straight from question frontmatter and joined into filesystem paths without validation. A malicious YAML can redirect reads/writes anywhere.
3. `env["FAKE_CLAUDE_NOTES"] = str(note_path)` is set unconditionally — a test-only env var leaking into production subprocess. Real `claude` ignores it; combined with the missing `assignment.json` write, the resumed worker has no way to learn which note to process.

**Depends on:** Task 1 (committer hardening — Task 4 uses `commit()`).

**Files:**
- Modify: `src/rufino/engine/process/batch/qa_resume.py` (substantial)
- Modify: `src/rufino/engine/process/batch/retry.py` (extract `_write_single_note_assignment` to module scope so qa_resume can reuse)
- Test: `tests/test_cli_qa_poll_resumption.py` (3 new tests + tighten existing)

### Steps

- [ ] **Step 1: Write the failing tests**

In `tests/test_cli_qa_poll_resumption.py`, modify the existing happy-path test and add three new ones:

```python
@pytest.mark.asyncio
async def test_qa_resume_lands_note_in_vault_canon(tmp_path, monkeypatch):
    """C1: after qa-poll, the augmented note must exist at destination_path."""
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "augment")
    vault, run_dir, question_file = _seed_pending_qa(tmp_path)  # helper writes a question

    from rufino.engine.process.batch.qa_resume import resume_pending_qa
    ok = await resume_pending_qa(vault_root=vault, question_file=question_file)

    assert ok is True
    # The destination_path template in _seed_pending_qa is "apuntes/{slug}.md"
    assert (vault / "apuntes" / "n1.md").exists()
    assert (vault / "apuntes" / "n1.md").read_text(encoding="utf-8").startswith("---")


@pytest.mark.asyncio
async def test_qa_resume_rejects_malicious_run_id(tmp_path):
    """C2 claude: run_id with path-traversal is rejected before any I/O."""
    vault = tmp_path / "vault"
    (vault / "questions").mkdir(parents=True)
    qfile = vault / "questions" / "q1.md"
    qfile.write_text(
        "---\n"
        "origin: process-batch\n"
        "run_id: ../../../etc\n"
        "worker_id: w001\n"
        "pending_note: x\n"
        "trigger: t\n"
        "context: c\n"
        "---\n"
        "answer: sí\n",
        encoding="utf-8",
    )

    from rufino.engine.process.batch.qa_resume import resume_pending_qa
    from rufino.engine.process.batch.errors import BatchError
    with pytest.raises(BatchError, match="unsafe identifier"):
        await resume_pending_qa(vault_root=vault, question_file=qfile)


@pytest.mark.asyncio
async def test_qa_resume_rejects_malicious_worker_id(tmp_path):
    """Same as above but the path-traversal lives in worker_id."""
    vault = tmp_path / "vault"
    (vault / "questions").mkdir(parents=True)
    qfile = vault / "questions" / "q1.md"
    qfile.write_text(
        "---\n"
        "origin: process-batch\n"
        "run_id: 2026-05-19T00-00-00Z-abcdef\n"
        "worker_id: ../escape\n"
        "pending_note: x\n"
        "trigger: t\n"
        "context: c\n"
        "---\n"
        "answer: sí\n",
        encoding="utf-8",
    )

    from rufino.engine.process.batch.qa_resume import resume_pending_qa
    from rufino.engine.process.batch.errors import BatchError
    with pytest.raises(BatchError, match="unsafe identifier"):
        await resume_pending_qa(vault_root=vault, question_file=qfile)


@pytest.mark.asyncio
async def test_qa_resume_does_not_leak_fake_claude_notes_env(tmp_path, monkeypatch):
    """H4 claude: FAKE_CLAUDE_NOTES must not be set by resume_pending_qa itself."""
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "augment")
    vault, run_dir, qfile = _seed_pending_qa(tmp_path)
    captured: dict = {}

    async def fake_run_claude(**kwargs):
        captured["env"] = kwargs["env"]
        from rufino.engine.process.batch.runner_helper import RunClaudeResult
        # Simulate that the worker did its job by writing the augmented file
        staging = kwargs["cwd"]
        (staging / "augmented").mkdir(parents=True, exist_ok=True)
        (staging / "augmented" / "n1.md").write_text(
            "---\nslug: n1\n---\n# n1\n", encoding="utf-8")
        (staging / "deltas").mkdir(parents=True, exist_ok=True)
        (staging / "deltas" / "n1.json").write_text("{}", encoding="utf-8")
        return RunClaudeResult(exit_code=0, stdout="", stderr="")

    monkeypatch.setattr("rufino.engine.process.batch.qa_resume.run_claude", fake_run_claude)
    from rufino.engine.process.batch.qa_resume import resume_pending_qa
    await resume_pending_qa(vault_root=vault, question_file=qfile)

    assert "FAKE_CLAUDE_NOTES" not in captured["env"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_cli_qa_poll_resumption.py -v
```

Expected: all 4 new tests FAIL (note in vault missing, no traversal rejection, env var still set).

- [ ] **Step 3: Implement the fix**

In `src/rufino/engine/process/batch/retry.py`, extract `_write_single_note_assignment` from wherever it lives in `_retry_one` to module scope so qa_resume can import it. (If it already is module scope, skip this and import it.)

In `src/rufino/engine/process/batch/qa_resume.py`, rewrite as:

```python
"""Resume a process-batch Q&A: re-invoke a single-note worker with the
user's answer injected, then VALIDATE and COMMIT the augmented note to
the vault canon before archiving the question.
"""
import json
import logging
import os
import re
import shutil
from pathlib import Path

import yaml

from rufino.engine.process.batch.committer import commit
from rufino.engine.process.batch.consolidator import ConsolidationPlan
from rufino.engine.process.batch.dispatcher import (
    SESSION_EXPIRED_EXIT_CODE,
    build_argv,
)
from rufino.engine.process.batch.errors import (
    BatchError,
    WorkerSessionExpiredError,
)
from rufino.engine.process.batch.planner import WorkerAssignment
from rufino.engine.process.batch.retry import _write_single_note_assignment
from rufino.engine.process.batch.runner_helper import run_claude
from rufino.engine.process.batch.validator import validate_one
from rufino.engine.process.batch.worker_prompt import (
    build_worker_system_prompt,
)
from rufino.engine.process.helpers.frontmatter import parse_frontmatter
from rufino.engine.process.manifest import parse_worker_manifest
from rufino.runtime.transaction_log import TransactionLog


log = logging.getLogger(__name__)


_PASSTHROUGH_EXTS = (".md", ".pdf", ".txt")
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]+$")


def _assert_safe_id(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise BatchError(f"unsafe identifier in question frontmatter ({field}={value!r})")
    return value


def _read_question(qfile: Path) -> dict:
    text = qfile.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    _, fm_text, body = text.split("---", 2)
    fm = yaml.safe_load(fm_text) or {}
    answer = ""
    for line in body.splitlines():
        if line.strip().startswith("answer:"):
            answer = line.split(":", 1)[1].strip()
            break
    fm["answer"] = answer
    return fm


_RESUME_APPENDIX = """

ANSWERED

El usuario respondió la pregunta de Q&A. Información:

  - trigger: {trigger}
  - contexto guardado: {context}
  - respuesta del usuario: {answer}

Rehacé esta nota con la respuesta integrada. Output normal: augmented/<slug>.md
y deltas/<slug>.json.
"""


async def resume_pending_qa(
    *, vault_root: Path, question_file: Path,
) -> bool:
    meta = _read_question(question_file)
    if not meta.get("answer"):
        return False
    if meta.get("origin") != "process-batch":
        return False

    run_id = _assert_safe_id(meta.get("run_id"), field="run_id")
    worker_id = _assert_safe_id(meta.get("worker_id"), field="worker_id")
    slug = _assert_safe_id(meta.get("pending_note"), field="pending_note")

    run_dir = vault_root / ".rufino" / "runs" / run_id
    if not run_dir.exists():
        return False

    plan_data = json.loads((run_dir / "plan.json").read_text(encoding="utf-8"))
    adapter_dir = Path(plan_data["adapter_dir"])
    manifest = parse_worker_manifest(
        (adapter_dir / "manifest.yaml").read_text(encoding="utf-8")
    )
    adapter_prompt = (
        (adapter_dir / "prompt.md").read_text(encoding="utf-8")
        if (adapter_dir / "prompt.md").exists() else ""
    )

    inbox = run_dir / "inbox"
    note_path: Path | None = None
    declared_input = meta.get("input_path")
    if isinstance(declared_input, str):
        candidate = run_dir / declared_input
        if candidate.exists() and candidate.resolve().is_relative_to(run_dir.resolve()):
            note_path = candidate
    if note_path is None:
        matches: list[Path] = []
        for ext in _PASSTHROUGH_EXTS:
            matches.extend(inbox.rglob(f"{slug}{ext}"))
        if not matches:
            log.warning(
                "qa-resume cannot locate note for slug=%s (run=%s); skipping",
                slug, run_id,
            )
            return False
        note_path = matches[0]

    staging_dir = run_dir / "workers" / worker_id
    staging_dir.mkdir(parents=True, exist_ok=True)
    # Clear stale leftovers so we don't falsely succeed on a previous run's file.
    for stale in (
        staging_dir / "augmented" / f"{slug}.md",
        staging_dir / "deltas" / f"{slug}.json",
        staging_dir / "pending" / f"{slug}.json",
    ):
        if stale.exists():
            stale.unlink()

    assignment = WorkerAssignment(
        worker_id=worker_id, group=note_path.parent.name, notes=(note_path,),
    )
    _write_single_note_assignment(staging_dir, assignment)

    base_prompt = build_worker_system_prompt(
        manifest=manifest, adapter_prompt_text=adapter_prompt,
        assignment=assignment, vault_slug="",
        staging_dir=staging_dir, vault_concepts_top_n=[],
        run_id=run_id,
    )
    appendix = _RESUME_APPENDIX.format(
        trigger=meta.get("trigger", ""),
        context=meta.get("context", ""),
        answer=meta["answer"],
    )

    env = os.environ.copy()
    argv = build_argv(
        system_prompt=base_prompt + appendix,
        vault_slug="",
    )
    result = await run_claude(
        argv=argv, cwd=staging_dir, env=env, timeout_seconds=300.0,
    )
    if result.exit_code == SESSION_EXPIRED_EXIT_CODE:
        raise WorkerSessionExpiredError(
            "Tu sesión Claude está expirada. Corré `claude login`."
        )
    if result.exit_code != 0:
        log.warning(
            "qa-resume worker exited %d for %s (run=%s): %s",
            result.exit_code, slug, run_id, result.stderr[:500],
        )
        return False

    aug = staging_dir / "augmented" / f"{slug}.md"
    delta = staging_dir / "deltas" / f"{slug}.json"
    if not aug.exists():
        log.warning(
            "qa-resume worker produced no augmented/%s.md (run=%s); leaving question in place",
            slug, run_id,
        )
        return False
    validation = validate_one(aug, delta, manifest)
    if not validation.passed:
        log.warning(
            "qa-resume validation failed for %s (run=%s): %s",
            slug, run_id, list(validation.errors),
        )
        return False

    # COMMIT the resumed note to the vault canon.
    fm, _ = parse_frontmatter(aug.read_text(encoding="utf-8"))
    variables = {k: v for k, v in fm.items() if isinstance(v, str)}
    variables.setdefault("slug", slug)
    try:
        dest_rel = manifest.destination_path.format(**variables)
    except KeyError as e:
        log.warning(
            "qa-resume cannot compute destination for %s: missing template key %s",
            slug, e,
        )
        return False

    rel_from = aug.relative_to(run_dir)
    plan = ConsolidationPlan(
        moves=[{"from": str(rel_from), "to": dest_rel}],
        concept_writes=[], tag_index_updates=[],
        log_entries=[f"batch-qa-resume run={run_id} slug={slug}"],
    )
    tx = TransactionLog(run_dir / f"qa-resume-{slug}.tx.json")
    commit(plan=plan, vault_root=vault_root, run_dir=run_dir, tx_log=tx)

    archived = vault_root / "questions" / "answered"
    archived.mkdir(parents=True, exist_ok=True)
    shutil.move(str(question_file), archived / question_file.name)
    return True
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_cli_qa_poll_resumption.py -v
pytest tests/test_batch_retry.py -v  # confirm extracted helper still works
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add src/rufino/engine/process/batch/qa_resume.py \
        src/rufino/engine/process/batch/retry.py \
        tests/test_cli_qa_poll_resumption.py
git commit -m "$(cat <<'EOF'
fix(qa-resume): commit augmented note + sanitize question YAML + drop test env var

After a Q&A is answered and qa-poll runs the resume worker, the augmented
note now goes through validate -> commit() via TransactionLog before the
question file is archived. Previously the note was orphaned in
.rufino/runs/.../augmented/ while the question moved to answered/.

Also validates run_id, worker_id, pending_note against [A-Za-z0-9._-]+
before joining them into paths (prevents traversal via crafted question
YAML), and drops the unconditional FAKE_CLAUDE_NOTES env var which was
a test-only leak. Uses retry._write_single_note_assignment so the real
worker actually receives the assignment.

Fixes Codex C1, Claude C1+C2, Claude H4.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Q&A pending hardening — degrade per-item, atomic writes, isinstance guards

**Why:** Four related defects in `qa_pending.py`:
1. `_validate_slug` raises `InvalidPendingSlugError` inside the write loop with no per-iteration catch → one malformed pending kills every remaining valid question.
2. `_existing_answer_filled` calls `parse_frontmatter` without try → a user-edited file with bad YAML crashes the whole write phase.
3. `_existing_answer_filled` uses `line.strip().startswith("answer:")` against the body, so a question text that *contains* the substring "answer:" is treated as filled.
4. `path.write_text(body)` is not atomic; a SIGKILL mid-write leaves a truncated file.
5. `collect_pending` accepts non-string `pending_note` values (LLM hallucination of an int) and the regex later raises `TypeError` instead of `InvalidPendingSlugError`.

**Files:**
- Modify: `src/rufino/engine/process/batch/qa_pending.py`
- Test: `tests/test_batch_qa_pending.py`

### Steps

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_batch_qa_pending.py`:

```python
def test_write_questions_continues_after_invalid_slug(tmp_path):
    """H1 claude: a single bad slug must not abort the whole batch."""
    pending = [
        PendingQA(slug="bad/../escape", pending_note="bad/../escape",
                  trigger="t", context="c", worker_id="w", run_id="r"),
        PendingQA(slug="good", pending_note="good", trigger="t",
                  context="c", worker_id="w", run_id="r"),
    ]
    result = write_questions_to_vault(pending, tmp_path)

    assert (tmp_path / "questions" / "good.md").exists()
    assert any("bad" in str(p) for p in result.failed)


def test_existing_answer_filled_does_not_crash_on_bad_frontmatter(tmp_path):
    """H2 claude: corrupted YAML in an existing question file is treated as not-filled."""
    qdir = tmp_path / "questions"
    qdir.mkdir()
    existing = qdir / "x.md"
    existing.write_text("---\nfoo: : :\n---\nanswer: stuff\n", encoding="utf-8")

    pending = [PendingQA(slug="x", pending_note="x", trigger="t",
                         context="c", worker_id="w", run_id="r")]
    # Must not raise; bad YAML => treat as not-filled => overwrite is allowed.
    write_questions_to_vault(pending, tmp_path)


def test_answer_detection_uses_frontmatter_not_body_substring(tmp_path):
    """M1 claude: a question whose text contains 'answer: x' is not filled."""
    qdir = tmp_path / "questions"
    qdir.mkdir()
    existing = qdir / "x.md"
    existing.write_text(
        "---\nslug: x\nanswer:\n---\n# Question\n\nHow do I write `answer: foo`?\n",
        encoding="utf-8",
    )

    pending = [PendingQA(slug="x", pending_note="x", trigger="t",
                         context="c", worker_id="w", run_id="r")]
    result = write_questions_to_vault(pending, tmp_path)
    # The question text contains "answer: foo" but the frontmatter answer is empty,
    # so we should overwrite.
    assert "answer:" in (qdir / "x.md").read_text(encoding="utf-8")
    assert result.skipped_existing == ()


def test_collect_pending_rejects_non_string_pending_note(tmp_path):
    """M6 claude: an LLM emitting a numeric pending_note is rejected cleanly."""
    workers = tmp_path / "workers" / "w001" / "pending"
    workers.mkdir(parents=True)
    (workers / "x.json").write_text(json.dumps({
        "pending_note": 42, "trigger": "t", "context": "c",
    }), encoding="utf-8")

    result = collect_pending(tmp_path)
    assert result == ()  # rejected silently; no TypeError


def test_question_writes_are_atomic(tmp_path, monkeypatch):
    """M2 claude: writes go through tmp + replace, not direct write_text."""
    qdir = tmp_path / "questions"
    qdir.mkdir()
    captured: list[Path] = []
    orig_replace = Path.replace

    def spy_replace(self, target):
        captured.append(target)
        return orig_replace(self, target)

    monkeypatch.setattr(Path, "replace", spy_replace)
    pending = [PendingQA(slug="x", pending_note="x", trigger="t",
                         context="c", worker_id="w", run_id="r")]
    write_questions_to_vault(pending, tmp_path)
    assert captured  # at least one atomic replace happened
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_batch_qa_pending.py::test_write_questions_continues_after_invalid_slug \
       tests/test_batch_qa_pending.py::test_existing_answer_filled_does_not_crash_on_bad_frontmatter \
       tests/test_batch_qa_pending.py::test_answer_detection_uses_frontmatter_not_body_substring \
       tests/test_batch_qa_pending.py::test_collect_pending_rejects_non_string_pending_note \
       tests/test_batch_qa_pending.py::test_question_writes_are_atomic -v
```

Expected: all 5 FAIL.

- [ ] **Step 3: Implement the fix**

In `src/rufino/engine/process/batch/qa_pending.py`:

1. Wrap the three `_validate_slug` calls in `write_questions_to_vault` in try/except, appending to `failed` and continuing.
2. Wrap `parse_frontmatter` in `_existing_answer_filled` with try/except → return `False`.
3. Change `_existing_answer_filled` to read the `answer` value from the **frontmatter dict** (`fm.get("answer", "")`) rather than line-scanning the body. The writer already includes `answer:` in frontmatter; harmonize.
4. Replace `path.write_text(body)` with:

```python
tmp = path.with_suffix(path.suffix + ".tmp")
tmp.write_text(body, encoding="utf-8")
tmp.replace(path)
```

5. In `collect_pending`, before constructing `PendingQA`, add:

```python
if not isinstance(data.get("pending_note"), str):
    log.warning("dropping %s: pending_note must be a string", p)
    continue
```

(Use the existing log warning pattern.)

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_batch_qa_pending.py -v
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add src/rufino/engine/process/batch/qa_pending.py tests/test_batch_qa_pending.py
git commit -m "$(cat <<'EOF'
fix(batch): harden qa_pending — per-item degrade, atomic writes, type guards

- Bad slugs are now logged + appended to failed[] instead of aborting
  the entire batch's Q&A write phase.
- _existing_answer_filled wraps parse_frontmatter in try/except so a
  corrupt YAML in an existing question file is treated as not-filled
  instead of crashing.
- Answer detection now reads frontmatter['answer'] rather than scanning
  the body for "answer:" substrings (avoids false positives in question
  text).
- Question writes use tmp + replace for atomicity.
- collect_pending isinstance-guards pending_note so a numeric value
  drops cleanly with a warning instead of raising TypeError later.

Fixes Claude H1, H2, M1, M2, M6.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Make mammoth/python-pptx optional or guard tests with importorskip

**Why:** On a clean machine where `pyproject.toml` deps haven't been pipx-installed, 9 tests crash with `ModuleNotFoundError: No module named 'mammoth'`. Codex hit this too. There is no CI today that catches this. Decision: keep `mammoth` and `python-pptx` as **hard deps** (they're cheap, listed already, and converters are a core feature), but add `pytest.importorskip` at the top of the converter/stager test modules so the suite is still partially usable in a stripped-down env. Add a CI install step note.

**Files:**
- Modify: `tests/test_batch_converters.py:1` (add importorskip)
- Modify: `tests/test_batch_stager.py` (add importorskip only to the docx/pptx-using tests)
- Modify: `tests/integration/test_batch_end_to_end.py` (add importorskip at top)
- Modify: `docs/getting-started.md` (note dependency install)
- Modify: `src/rufino/engine/process/batch/converters.py:20-40` (guard imports with a clear error if used without deps)

### Steps

- [ ] **Step 1: Write the failing test**

In a clean env (or by uninstalling locally — do not actually do that; instead simulate via a fixture):

```python
# tests/test_batch_converters.py - new test at top
def test_converters_module_importable_without_mammoth(monkeypatch):
    """If mammoth is missing, importing converters must still succeed; only the
    docx call should raise a clear error."""
    import sys
    monkeypatch.setitem(sys.modules, "mammoth", None)
    # Reimport to simulate fresh import
    if "rufino.engine.process.batch.converters" in sys.modules:
        del sys.modules["rufino.engine.process.batch.converters"]
    from rufino.engine.process.batch import converters  # must not raise
    with pytest.raises(RuntimeError, match="mammoth is required"):
        converters.convert_to_markdown(Path("x.docx"))
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_batch_converters.py::test_converters_module_importable_without_mammoth -v
```

Expected: FAIL (today `converters.py` imports `mammoth` at module load).

- [ ] **Step 3: Implement the fix**

In `src/rufino/engine/process/batch/converters.py`, move imports of `mammoth` and `pptx` into the functions that use them, with a clear runtime error:

```python
def _docx_to_md(src: Path) -> str:
    try:
        import mammoth  # noqa: WPS433  (lazy import is intentional)
    except ImportError as e:
        raise RuntimeError(
            "mammoth is required for .docx conversion. "
            "Install with `pip install -e .` (it is in pyproject.toml)."
        ) from e
    # ... existing body
```

(Same pattern for `pptx`.)

In `tests/test_batch_converters.py`, add at the top:

```python
pytest.importorskip("mammoth")
pytest.importorskip("pptx")
```

In `tests/test_batch_stager.py`, only guard the docx/pptx-using tests with `@pytest.mark.skipif(...)` or a module-level `importorskip` if the whole file uses them. Read the file first and decide.

In `tests/integration/test_batch_end_to_end.py`, add at the top:

```python
pytest.importorskip("mammoth")
pytest.importorskip("pptx")
```

In `docs/getting-started.md`, add a sentence after the install instructions:

```markdown
> `process-batch` requiere `mammoth` y `python-pptx` (declarados en
> `pyproject.toml`). Si te aparece `ModuleNotFoundError`, reinstalá con
> `./install.sh` o `pipx install -e .`.
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_batch_converters.py tests/test_batch_stager.py \
       tests/integration/test_batch_end_to_end.py -v
```

Expected: all green when deps are installed; the importorskip lines silently skip in their absence.

- [ ] **Step 5: Commit**

```bash
git add src/rufino/engine/process/batch/converters.py \
        tests/test_batch_converters.py tests/test_batch_stager.py \
        tests/integration/test_batch_end_to_end.py \
        docs/getting-started.md
git commit -m "$(cat <<'EOF'
fix(batch): lazy-import mammoth/pptx + importorskip in tests

Module load of converters.py no longer requires mammoth/python-pptx;
they are imported lazily inside the conversion functions with a clear
RuntimeError if missing. Tests gain pytest.importorskip guards so a
stripped-down env doesn't collapse the entire suite. Docs note the
install requirement.

Fixes Claude C3.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Docs sweep — cli-reference, v0.0.2 staleness, batch_size

**Why:** Three doc gaps that misrepresent the v0.1.0 release:
1. `docs/cli-reference.md` has no `process-batch` section — and it's the canonical command doc, linked from README.
2. Seven+ files still say "v0.0.2" / "stubbed en v0.0.2" / "qa-poll refuses to consume answers" / "process --mode full exits 2 in v0.0.2". The code is v0.1.0 and most of those features now operate.
3. `docs/writing-adapters.md` Process manifest schema omits `batch_size`.

**Files:**
- Modify: `docs/cli-reference.md` (add `process-batch` section; sweep v0.0.2)
- Modify: `docs/getting-started.md`, `docs/architecture.md`, `docs/concepts.md`, `docs/runtime.md`, `docs/troubleshooting.md` (sweep v0.0.2 references)
- Modify: `docs/writing-adapters.md:172-206` (add `batch_size`)
- Modify: `docs/primitives/process.md` (verify "Estado v0.1.0" wording — should not regress)
- Modify: `README.md:140` (link to cli-reference section)

### Steps

- [ ] **Step 1: Inventory the v0.0.2 references**

Run:

```bash
grep -rn "v0\.0\.2\|0\.0\.2\|stubbed\|stub\|stub-only\|refuses to consume" docs/ README.md
```

Expected: list of files and line numbers covering 7-10 hits. Record them.

- [ ] **Step 2: Add `process-batch` section to cli-reference.md**

Insert (after the existing `rufino process` section, before `rufino qa-poll`):

```markdown
## `rufino process-batch`

Procesa un corpus entero (directorio o ZIP) generando notas augmentadas
en paralelo vía workers de Claude.

### Sinopsis

    rufino process-batch <source> [options]

### Argumentos

- `<source>` — directorio o archivo `.zip` con el corpus a procesar.

### Opciones

| Flag | Descripción | Default |
|---|---|---|
| `--adapter <dir>` | Worker adapter a usar | (último materializado) |
| `--vault <dir>` | Vault destino | `$RUFINO_VAULT` |
| `--workers <N>` | Workers paralelos | `min(4, n_workers)` |
| `--batch-size <N>` | Notas por worker (override del manifest) | manifest |
| `--dry-run` | Solo stage + plan, sin ejecutar workers | `False` |
| `--skip-consolidator` | Saltea consolidador y usa naive plan | `False` |

### Exit codes

- `0` — run completo, commit aplicado.
- `1` — error de runtime (corpus vacío, manifest inválido, batch failure).
- `124` — un worker hizo timeout.
- `127` — `claude` binary no encontrado en PATH.
- session-expired — exit code 1 con mensaje pidiendo `claude login`.

### Ejemplos

    rufino process-batch ~/Downloads/corpus.zip \
      --adapter ~/.rufino/adapters/process/notas \
      --vault ~/vault --workers 4

    rufino process-batch ./corpus --dry-run
```

- [ ] **Step 3: Sweep v0.0.2 references**

For each file in the inventory, replace stale claims. Common patterns:

- `"v0.0.2"` → `"v0.1.0"` (where it refers to current version)
- `"stubbed en v0.0.2 — exits 2"` (single-note `--mode full`) → keep accurate: "single-note `--mode full` queda diferido; usá `process-batch` para procesar en lote"
- `"qa-poll refuses to consume answers until resumption is wired"` → `"qa-poll resuelve preguntas originadas en process-batch; ver Task T16 en el plan original"`
- `"rufino version → 0.0.3"` (in `docs/getting-started.md:50,163`) → `"rufino version → 0.1.0"`

Do not introduce new claims — just update what's there. If a sentence is no longer relevant, delete it cleanly.

- [ ] **Step 4: Add `batch_size` to writing-adapters.md**

In `docs/writing-adapters.md`, around line 172-206 (the Process manifest YAML block), add `batch_size` with its constraints:

```markdown
- `batch_size: <int>` — número de notas por worker. Default: 10. Debe
  ser un entero positivo (>=1). Lo overridea el flag `--batch-size`.
```

Also update the example manifest YAML block to show the field.

- [ ] **Step 5: Update README link**

In `README.md:140`, change the terse line to:

```markdown
- `rufino process-batch <zip-or-dir>` — Batch-procesa un corpus a notas
  augmentadas vía Claude workers (v0.1.0). Ver
  [`docs/cli-reference.md#rufino-process-batch`](docs/cli-reference.md).
```

- [ ] **Step 6: Verify with a re-grep**

```bash
grep -rn "v0\.0\.2\|stubbed" docs/ README.md
```

Expected: only historical references (e.g., commit messages quoted in the codereview docs, or design specs that intentionally narrate v0.0.2 → v0.1.0 transitions). All current-state claims should be gone.

- [ ] **Step 7: Commit**

```bash
git add docs/ README.md
git commit -m "$(cat <<'EOF'
docs: add process-batch to cli-reference, sweep v0.0.2 staleness, document batch_size

- docs/cli-reference.md gains a full rufino process-batch section
  (sinopsis, flags, exit codes, examples).
- Seven+ files swept for v0.0.2 references that contradicted current
  v0.1.0 behavior (qa-poll resumption, process-batch availability,
  getting-started version output).
- docs/writing-adapters.md Process manifest schema now documents the
  batch_size field.
- README links directly to the new cli-reference section.

Fixes Claude C4, C5, H9.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Consolidator happy path test + dispatcher cancellation test

**Why:** `run_consolidator` has validation tests and a fallback test, but no test where a `consolidation-plan.json` is actually produced by the worker, parsed by the runner, and used by commit. Likewise the dispatcher docstring documents cancellation behavior ("siblings cannot honor cancellation until their subprocess returns") that no test verifies.

**Files:**
- Modify: `tests/fixtures/fake_claude/claude` (add `consolidate` mode)
- Test: `tests/test_batch_runner.py` (consolidator happy path)
- Test: `tests/test_batch_dispatcher.py` (cancellation behavior)

### Steps

- [ ] **Step 1: Add `consolidate` mode to fake_claude**

In `tests/fixtures/fake_claude/claude`, add a branch that detects an env var or stdin marker indicating the consolidator was invoked, and writes a valid `consolidation-plan.json` to cwd. Look at existing `augment` mode for the shape.

```python
elif os.environ.get("FAKE_CLAUDE_MODE") == "consolidate":
    # Synthesize a valid plan from the augmented files in cwd
    augmented_root = Path.cwd()
    moves = []
    for worker_dir in augmented_root.glob("workers/*/augmented"):
        for aug in worker_dir.glob("*.md"):
            slug = aug.stem
            rel = aug.relative_to(augmented_root)
            moves.append({"from": str(rel), "to": f"apuntes/{slug}.md"})
    plan = {
        "moves": moves, "concept_writes": [],
        "tag_index_updates": [], "log_entries": ["fake consolidator"],
    }
    Path("consolidation-plan.json").write_text(json.dumps(plan), encoding="utf-8")
    sys.exit(0)
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_batch_runner.py`:

```python
@pytest.mark.asyncio
async def test_runner_uses_consolidator_plan_when_available(tmp_path, monkeypatch):
    """H10 claude: consolidator happy path must drive commit, not naive fallback."""
    # The fake_claude script reads FAKE_CLAUDE_MODE per invocation; we set
    # augment for workers and consolidate for the consolidator step. The
    # script keys off the cwd / argv to differentiate — verify via stdout marker.
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "augment_then_consolidate")
    vault, adapter, source = _make_minimal_setup(tmp_path)

    result = await run_batch(
        source=source, adapter_dir=adapter, vault_root=vault,
        workers=1, batch_size=1, dry_run=False,
        skip_consolidator=False, timeout_seconds=10.0,
    )

    assert result.notes_ok >= 1
    # Confirm via run.json that the log entry came from the consolidator,
    # not the naive plan.
    run_dir = vault / ".rufino" / "runs" / result.run_id
    plan_log = (run_dir / "commit.tx.json").read_text(encoding="utf-8")
    assert "fake consolidator" in plan_log
```

Append to `tests/test_batch_dispatcher.py`:

```python
@pytest.mark.asyncio
async def test_dispatch_session_expired_one_worker_does_not_hang_siblings(tmp_path, monkeypatch):
    """M15 claude: when w001 returns session_expired, w002 must finish (or be
    cleanly cancellable) without leaving zombie subprocesses."""
    # Use a marker file: w001 writes 'expired' marker; w002 must produce a real output.
    # Verify by inspecting <run_dir>/workers/w002/augmented/.
    monkeypatch.setenv("FAKE_CLAUDE_MODE_W001", "session_expired")
    monkeypatch.setenv("FAKE_CLAUDE_MODE_W002", "augment")
    # ... build a plan with 2 workers and dispatch
    # assert that WorkerSessionExpiredError is raised AND w002's augmented file exists
```

(Adjust fake_claude to read per-worker env vars by inspecting its `cwd` to figure out the worker_id.)

- [ ] **Step 3: Run tests to verify they fail**

```bash
pytest tests/test_batch_runner.py::test_runner_uses_consolidator_plan_when_available \
       tests/test_batch_dispatcher.py::test_dispatch_session_expired_one_worker_does_not_hang_siblings -v
```

Expected: both FAIL (fake_claude doesn't have the modes; dispatcher behavior unverified).

- [ ] **Step 4: Implement the fakes + verify passing**

The dispatcher itself does not need changes — only the test fixtures. Once fake_claude supports the modes, the tests should pass and pin the documented behavior.

```bash
pytest tests/test_batch_dispatcher.py tests/test_batch_runner.py -v
```

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/fake_claude/claude \
        tests/test_batch_runner.py tests/test_batch_dispatcher.py
git commit -m "$(cat <<'EOF'
test(batch): cover consolidator happy path + dispatcher session-expired cancellation

Adds 'consolidate' mode to fake_claude and a runner test that asserts
the consolidator plan (not the naive fallback) drives commit when
skip_consolidator=False. Also pins dispatcher behavior when one worker
returns session_expired mid-flight: siblings must complete or be
cleanly cancellable.

Fixes Claude H10, M15.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: E2E test expansion — ZIP input, CLI driver, negative path

**Why:** `tests/integration/test_batch_end_to_end.py` is a single 77-line test labelled "mixed formats" that bypasses the CLI, skips the consolidator, omits ZIP and `.txt`, and uses a loose `>= 3` assertion. None of the headline production paths (CLI → exit code mapping; ZIP → stager; retry → failed/) are end-to-end verified.

**Files:**
- Modify: `tests/integration/test_batch_end_to_end.py` (add 3 parametrized cases or 3 separate tests)

### Steps

- [ ] **Step 1: Write the failing tests**

Add to `tests/integration/test_batch_end_to_end.py`:

```python
@pytest.mark.asyncio
async def test_e2e_zip_input_through_cli(tmp_path, monkeypatch):
    """E2E with ZIP corpus driven by the CLI; assert exit code 0 + vault state."""
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "augment")
    vault = tmp_path / "vault"
    adapter = _make_adapter(tmp_path / "adapter")
    # Build a ZIP with md + docx + txt
    zip_path = _build_test_zip(tmp_path)

    from click.testing import CliRunner
    from rufino.cli import cli
    runner = CliRunner()
    result = runner.invoke(cli, [
        "process-batch", str(zip_path),
        "--adapter", str(adapter), "--vault", str(vault),
        "--skip-consolidator",
    ])

    assert result.exit_code == 0, result.output
    landed = list((vault / "apuntes").glob("*.md"))
    assert len(landed) == 3
    slugs = {p.stem for p in landed}
    assert slugs == {"md_note", "docx_note", "txt_note"}


@pytest.mark.asyncio
async def test_e2e_retry_exhausts_files_go_to_failed(tmp_path, monkeypatch):
    """E2E negative path: worker always produces bad output → after retry, slug in failed/."""
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "augment_bad")
    vault, adapter, source = _make_minimal_setup(tmp_path)

    result = await run_batch(
        source=source, adapter_dir=adapter, vault_root=vault,
        workers=1, batch_size=1, dry_run=False,
        skip_consolidator=True, timeout_seconds=10.0,
    )

    assert result.notes_failed >= 1
    run_dir = vault / ".rufino" / "runs" / result.run_id
    failed_dirs = list((run_dir / "failed").glob("*"))
    assert failed_dirs, "expected failed/<slug>/ markers"


@pytest.mark.asyncio
async def test_e2e_cli_returns_127_when_claude_missing(tmp_path, monkeypatch):
    """CLI exit code mapping for missing claude binary."""
    # Strip claude from PATH
    monkeypatch.setenv("PATH", "/usr/bin")
    vault, adapter, source = _make_minimal_setup(tmp_path)

    from click.testing import CliRunner
    from rufino.cli import cli
    runner = CliRunner()
    result = runner.invoke(cli, [
        "process-batch", str(source),
        "--adapter", str(adapter), "--vault", str(vault),
    ])

    assert result.exit_code == 127
```

Helper `_build_test_zip` creates a ZIP with one `.md`, one `.docx`, one `.txt`.

- [ ] **Step 2: Run tests to verify they fail or pass**

```bash
pytest tests/integration/test_batch_end_to_end.py -v
```

Expected: the ZIP+CLI test fails if the CLI path has a bug; the failed/ test fails if Task 2 (validator assignment-aware) didn't fix the silent-failure case; the 127 test should pass already given the existing FileNotFoundError handler.

- [ ] **Step 3: Tighten the existing test**

In the existing `test_full_pipeline_end_to_end`, change `assert result.notes_ok >= 3` to `assert result.notes_ok == 4` (or assert on the specific slug set).

- [ ] **Step 4: Run all integration tests**

```bash
pytest tests/integration/ -v
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_batch_end_to_end.py
git commit -m "$(cat <<'EOF'
test(e2e): cover ZIP+CLI happy path, retry exhaustion to failed/, missing claude

Adds three integration tests exercising the production paths that the
previous single e2e test bypassed: ZIP input through the CLI driver,
retry-exhausted notes landing in failed/, and the exit-code-127 path
when claude is not in PATH. Tightens the existing test's loose >= 3
assertion to == 4.

Fixes Claude H8.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Test infra cleanup — conftest fixtures, CWD-independent paths

**Why:** `FAKE_DIR` and `_make_adapter` are duplicated across 6 test files; `Path("tests/fixtures/...")` (relative to CWD) appears in 3 files and breaks when pytest is run from a different directory.

**Files:**
- Modify: `tests/conftest.py` (add shared fixtures)
- Modify: `tests/test_batch_retry.py`, `tests/test_batch_stager.py`, `tests/integration/test_batch_end_to_end.py` (absolute paths)
- Modify: 6 test files (consume conftest helpers)

### Steps

- [ ] **Step 1: Move shared helpers to conftest**

In `tests/conftest.py`, add:

```python
from pathlib import Path

import pytest


FAKE_CLAUDE_DIR = (Path(__file__).parent / "fixtures" / "fake_claude").resolve()
BATCH_FIXTURES = (Path(__file__).parent / "fixtures" / "batch").resolve()


@pytest.fixture(autouse=False)
def fake_claude_on_path(monkeypatch):
    """Prepend the fake_claude fixture directory to PATH for tests that need it."""
    monkeypatch.setenv("PATH", f"{FAKE_CLAUDE_DIR}:{__import__('os').environ['PATH']}")
    yield


@pytest.fixture
def batch_adapter(tmp_path):
    """Factory: build a minimal Process worker adapter dir."""
    def _make(adapter_dir: Path | None = None, **manifest_overrides):
        adapter_dir = adapter_dir or (tmp_path / "adapter")
        adapter_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "name": "test-process",
            "kind": "process",
            "destination_path": "apuntes/{slug}.md",
            "output_schema": {"required": {"slug": "string"}},
            "batch_size": manifest_overrides.get("batch_size", 10),
        }
        manifest.update(manifest_overrides)
        # Write YAML
        import yaml
        (adapter_dir / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
        (adapter_dir / "prompt.md").write_text("# test prompt\n", encoding="utf-8")
        return adapter_dir
    return _make
```

- [ ] **Step 2: Replace duplicated helpers in test files**

In each of `tests/test_batch_runner_helper.py`, `tests/test_batch_dispatcher.py`, `tests/test_batch_runner.py`, `tests/test_cli_process_batch.py`, `tests/test_batch_retry.py`, `tests/integration/test_batch_end_to_end.py`:

- Replace `FAKE_DIR = Path("tests/fixtures/fake_claude").resolve()` (or similar) with the conftest fixture.
- Replace local `_make_adapter` with `batch_adapter` fixture.

In `tests/test_batch_stager.py:78,93`, replace `Path("tests/fixtures/batch/hello.docx")` with `BATCH_FIXTURES / "hello.docx"`.

- [ ] **Step 3: Verify with cd-from-tmp**

```bash
cd /tmp && pytest /Users/val/Files/codeProjects/rufino-framework/tests/test_batch_stager.py -v
cd /tmp && pytest /Users/val/Files/codeProjects/rufino-framework/tests/test_batch_retry.py -v
```

Expected: all green even from `/tmp`.

- [ ] **Step 4: Run the whole batch suite**

```bash
pytest tests/test_batch_*.py tests/test_cli_process_batch.py tests/integration/ -v
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add tests/conftest.py tests/test_batch_*.py tests/test_cli_process_batch.py \
        tests/integration/test_batch_end_to_end.py
git commit -m "$(cat <<'EOF'
test(batch): consolidate FAKE_DIR + _make_adapter helpers in conftest, fix CWD-relative paths

Moves the duplicated fake_claude PATH setup and minimal-adapter
factory into tests/conftest.py. Replaces three test files' CWD-relative
fixture paths with __file__-anchored absolute paths so pytest works
from any working directory.

Fixes Claude M13, M14.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: Cleanup sweep — nits, constants, deferred markers

**Why:** Catch the rest of the Medium/Low findings as a single hygiene pass. These individually are too small to deserve a task each but collectively improve maintainability.

**Files:**
- Modify: `src/rufino/engine/process/manifest.py` (constant for default batch_size)
- Modify: `src/rufino/engine/process/batch/dispatcher.py` (extract worker kickoff string)
- Modify: `src/rufino/engine/process/batch/retry.py` (comment _STDERR_TAIL_CHARS)
- Modify: `src/rufino/engine/process/batch/runner_helper.py` (comment unbounded capture)
- Modify: `src/rufino/engine/process/batch/stager.py` (freeze StagedCorpus or builder pattern)
- Modify: `src/rufino/engine/process/batch/worker_prompt.py` (qa_triggers block)
- Modify: `migrations/0.0.3-to-0.1.0.sh` (mkdir -p defensive)
- Modify: `CLAUDE.md` (add deferred list section)
- Modify: `tests/test_batch_planner.py` (remove unused import; loosen exact-size assertion)
- Modify: `tests/test_batch_validator.py` (loosen BrokenManifest assertion)

### Steps

- [ ] **Step 1: Apply the small fixes**

1. In `src/rufino/engine/process/manifest.py`, add `_DEFAULT_BATCH_SIZE = 10` at module top; replace the two literal `10` occurrences.
2. In `src/rufino/engine/process/batch/dispatcher.py:43`, extract `"Procesá las notas listadas en assignment.json siguiendo el system prompt."` to a module constant `_WORKER_KICKOFF` and use it in both dispatcher and retry.
3. In `src/rufino/engine/process/batch/retry.py:30`, add a comment above `_STDERR_TAIL_CHARS = 500`: `# LLM stderr is rarely useful past first KB; 500 chars keeps error.json small.`
4. In `src/rufino/engine/process/batch/runner_helper.py:30-37`, add a TODO comment: `# TODO(v0.2): bound stdout/stderr capture — a misbehaving claude could OOM us.`
5. In `src/rufino/engine/process/batch/stager.py:30-33`, leave `StagedCorpus` mutable but add a docstring noting that mutation is intentional during staging; rest of code uses frozen dataclasses.
6. In `src/rufino/engine/process/batch/worker_prompt.py`, add a `qa_triggers_block` similar to the existing `vocab_block`, listing manifest qa_triggers by name+condition. Update the prompt template to include it. Adjust the existing tests if any string assertion breaks.
7. In `migrations/0.0.3-to-0.1.0.sh`, add `mkdir -p "${RUFINO_HOME}"` at the top.
8. In `CLAUDE.md`, add a "Deferred for v0.2+" section listing: unbounded stdout capture, advisory lock per vault, worker_id `:04d` width, `transform_hook` execution, Ingest `emit_augmented`, single-note `--mode full`.
9. In `tests/test_batch_planner.py`, remove `import pytest` if unused; replace `assert sizes == [10, 10, 5]` with `assert sum(sizes) == 25 and max(sizes) <= 10`.
10. In `tests/test_batch_validator.py:164-180`, loosen the `BrokenManifest` assertion from `pytest.raises(AttributeError)` to `pytest.raises((AttributeError, TypeError))` or to checking that whatever raises is NOT a `ValidationError`/schema-related class.

- [ ] **Step 2: Run the whole suite**

```bash
pytest -v
```

Expected: all 90+ tests green. If `worker_prompt` tests fail because they assert on specific strings that the new `qa_triggers_block` perturbs, update those assertions (or use `in` matches rather than `==`).

- [ ] **Step 3: Run ruff and black**

```bash
ruff check src/ tests/
black --check src/ tests/
```

Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "$(cat <<'EOF'
chore(batch): cleanup pass — constants, comments, deferred markers

- Default batch_size as a named constant
- Extract worker kickoff string from duplicated literal
- Comment _STDERR_TAIL_CHARS rationale
- TODO(v0.2) for unbounded stdout/stderr capture
- StagedCorpus mutability documented
- Worker prompt now lists qa_triggers explicitly (matches plan intent)
- Migration script mkdir -p defensive
- CLAUDE.md "Deferred for v0.2+" section
- Loosened a couple of overspecific test assertions

Fixes Claude M3-M11 (subset), nits.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Final verification

After all 11 tasks land, run:

```bash
pytest -v
ruff check src/ tests/
black --check src/ tests/
```

Then re-grep the codereview docs and confirm every "🔴 Critical" and "🟠 High" finding has a matching commit. Update `docs/codereview/review-claude.md` with a footer noting the date the fixes shipped:

```markdown
---

## Fix log

- 2026-05-19 — initial review
- YYYY-MM-DD — fixes applied (see plan `docs/superpowers/plans/2026-05-19-process-batch-review-fixes.md`)
```

Same for `docs/codereview/codex.md`.

Bump version to `0.1.1` (or `0.2.0` if any task is breaking) in `src/rufino/version.py` and `pyproject.toml`, add a migration marker `migrations/0.1.0-to-0.1.1.sh` if needed.
