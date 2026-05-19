import asyncio
import os
from pathlib import Path

import pytest

from rufino.engine.process.batch.dispatcher import (
    DispatchOutcome,
    WorkerOutcome,
    dispatch,
)
from rufino.engine.process.batch.errors import WorkerSessionExpiredError
from rufino.engine.process.batch.planner import WorkerAssignment, Plan


FAKE_DIR = (Path(__file__).parent / "fixtures" / "fake_claude").resolve()


@pytest.fixture(autouse=True)
def _path_with_fake_claude(monkeypatch):
    monkeypatch.setenv("PATH", str(FAKE_DIR) + os.pathsep + os.environ["PATH"])


def _staged_note(tmp_path: Path, group: str, slug: str) -> Path:
    p = tmp_path / "inbox" / group / f"{slug}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"# {slug}\n")
    return p


def _plan_with(notes_by_worker: dict[str, list[Path]]) -> Plan:
    workers = tuple(
        WorkerAssignment(worker_id=wid, group="g", notes=tuple(ns))
        for wid, ns in notes_by_worker.items()
    )
    return Plan(run_id="r1", adapter_dir="/a", workers=workers)


def test_dispatch_writes_outputs(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "augment")
    n1 = _staged_note(tmp_path, "g", "n1")
    n2 = _staged_note(tmp_path, "g", "n2")
    plan = _plan_with({"w001": [n1, n2]})

    outcome = asyncio.run(dispatch(
        plan=plan, run_dir=tmp_path,
        system_prompt_for=lambda a: f"prompt for {a.worker_id}",
        vault_slug="v", max_workers=2, timeout_seconds=30,
    ))
    assert isinstance(outcome, DispatchOutcome)
    assert len(outcome.workers) == 1
    assert outcome.workers[0].exit_code == 0

    staging = tmp_path / "workers" / "w001"
    assert (staging / "augmented" / "n1.md").exists()
    assert (staging / "augmented" / "n2.md").exists()
    assert (staging / "deltas" / "n1.json").exists()


def test_dispatch_parallel_smoke(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "augment")
    plan = _plan_with({
        f"w{i:03d}": [_staged_note(tmp_path, "g", f"n{i}")]
        for i in range(1, 5)
    })
    outcome = asyncio.run(dispatch(
        plan=plan, run_dir=tmp_path,
        system_prompt_for=lambda a: "p", vault_slug="v",
        max_workers=2, timeout_seconds=30,
    ))
    assert len(outcome.workers) == 4
    assert all(w.exit_code == 0 for w in outcome.workers)


def test_dispatch_session_expired_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "session_expired")
    n = _staged_note(tmp_path, "g", "n1")
    plan = _plan_with({"w001": [n]})
    with pytest.raises(WorkerSessionExpiredError):
        asyncio.run(dispatch(
            plan=plan, run_dir=tmp_path,
            system_prompt_for=lambda a: "p", vault_slug="v",
            max_workers=1, timeout_seconds=30,
        ))


def test_dispatch_empty_outputs_ok(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "empty")
    n = _staged_note(tmp_path, "g", "n1")
    plan = _plan_with({"w001": [n]})
    outcome = asyncio.run(dispatch(
        plan=plan, run_dir=tmp_path,
        system_prompt_for=lambda a: "p", vault_slug="v",
        max_workers=1, timeout_seconds=30,
    ))
    assert outcome.workers[0].exit_code == 0


def test_dispatch_session_expired_one_worker_does_not_hang_siblings(
    tmp_path, monkeypatch,
):
    """M15 claude: when w001 returns session_expired, w002 must finish (or be
    cleanly cancellable) without leaving zombie subprocesses.

    Both workers are launched concurrently under ``max_workers=2``. w001's
    fake subprocess exits 41 immediately (session_expired), which the
    dispatcher maps to WorkerSessionExpiredError. w002 runs ``augment`` —
    fake_claude is a single Python invocation, so by the time
    ``asyncio.gather`` awaits the threaded subprocess, w002 has already
    written its outputs. The dispatcher's docstring documents that
    siblings can't honor cancellation until their subprocess returns, so
    we verify *the side effect*: w002's augmented/<slug>.md is on disk
    AND the expired-session exception still surfaces to the caller.

    Bounded timeout (5s) keeps a regression from hanging the suite.
    """
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "augment_then_consolidate")  # default branch
    # Per-worker overrides: dispatcher writes assignment.json with worker_id,
    # fake_claude reads it and looks up FAKE_CLAUDE_MODE_<WID_UPPER>.
    monkeypatch.setenv("FAKE_CLAUDE_MODE_W001", "session_expired")
    monkeypatch.setenv("FAKE_CLAUDE_MODE_W002", "augment")
    n1 = _staged_note(tmp_path, "g", "n1")
    n2 = _staged_note(tmp_path, "g", "n2")
    plan = _plan_with({"w001": [n1], "w002": [n2]})

    async def _run() -> None:
        await asyncio.wait_for(
            dispatch(
                plan=plan, run_dir=tmp_path,
                system_prompt_for=lambda a: f"p:{a.worker_id}",
                vault_slug="v",
                max_workers=2, timeout_seconds=5,
            ),
            timeout=15,
        )

    with pytest.raises(WorkerSessionExpiredError):
        asyncio.run(_run())

    # Side-effect: w002 completed its work despite the sibling crash. The
    # dispatcher cannot cancel an in-flight subprocess.run thread, so the
    # documented contract is that w002 either completes or is cleanly
    # cancellable — empirically, since augment is fast, the file lands.
    w002_aug = tmp_path / "workers" / "w002" / "augmented" / "n2.md"
    assert w002_aug.exists(), (
        "w002 (mode=augment) should have produced its augmented file "
        "before the dispatch task was cancelled by w001's session_expired"
    )
