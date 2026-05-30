import asyncio
from pathlib import Path

import pytest

from rufino.engine.process.batch import dispatcher as dispatcher_mod
from rufino.engine.process.batch.dispatcher import (
    DispatchOutcome,
    WorkerOutcome,
    build_argv,
    dispatch,
)
from rufino.engine.process.batch.errors import WorkerSessionExpiredError
from rufino.engine.process.batch.planner import WorkerAssignment, Plan
from rufino.engine.process.batch.runner_helper import ClaudeResult


@pytest.fixture(autouse=True)
def _path_with_fake_claude(fake_claude_on_path):
    """Autouse delegate to shared conftest fixture (FAKE_CLAUDE_DIR on PATH)."""
    yield


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


def test_build_argv_defaults_to_sonnet():
    """Workers run on Sonnet by default — Opus is needlessly slow for the
    per-note augmentation task. The flag pins it explicitly so the worker
    never inherits the operator's interactive default model."""
    argv = build_argv(system_prompt="p", vault_slug="v")
    assert "--model" in argv
    assert argv[argv.index("--model") + 1] == "sonnet"


def test_build_argv_model_override():
    argv = build_argv(system_prompt="p", vault_slug="v", model="opus")
    assert argv[argv.index("--model") + 1] == "opus"


def test_dispatch_propagates_model_to_argv(tmp_path, monkeypatch):
    """dispatch threads the chosen model down to each worker's argv."""
    captured: dict[str, list[str]] = {}

    async def _spy(*, argv, cwd, env, timeout_seconds):
        captured["argv"] = argv
        return ClaudeResult(exit_code=0)

    monkeypatch.setattr(dispatcher_mod, "run_claude", _spy)
    n = _staged_note(tmp_path, "g", "n1")
    plan = _plan_with({"w0001": [n]})

    asyncio.run(dispatch(
        plan=plan, run_dir=tmp_path,
        system_prompt_for=lambda a: "p", vault_slug="v",
        max_workers=1, timeout_seconds=30, model="haiku",
    ))
    assert captured["argv"][captured["argv"].index("--model") + 1] == "haiku"


def test_dispatch_writes_outputs(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "augment")
    n1 = _staged_note(tmp_path, "g", "n1")
    n2 = _staged_note(tmp_path, "g", "n2")
    plan = _plan_with({"w0001": [n1, n2]})

    outcome = asyncio.run(dispatch(
        plan=plan, run_dir=tmp_path,
        system_prompt_for=lambda a: f"prompt for {a.worker_id}",
        vault_slug="v", max_workers=2, timeout_seconds=30,
    ))
    assert isinstance(outcome, DispatchOutcome)
    assert len(outcome.workers) == 1
    assert outcome.workers[0].exit_code == 0

    staging = tmp_path / "workers" / "w0001"
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
    plan = _plan_with({"w0001": [n]})
    with pytest.raises(WorkerSessionExpiredError):
        asyncio.run(dispatch(
            plan=plan, run_dir=tmp_path,
            system_prompt_for=lambda a: "p", vault_slug="v",
            max_workers=1, timeout_seconds=30,
        ))


def test_dispatch_empty_outputs_ok(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "empty")
    n = _staged_note(tmp_path, "g", "n1")
    plan = _plan_with({"w0001": [n]})
    outcome = asyncio.run(dispatch(
        plan=plan, run_dir=tmp_path,
        system_prompt_for=lambda a: "p", vault_slug="v",
        max_workers=1, timeout_seconds=30,
    ))
    assert outcome.workers[0].exit_code == 0


def test_dispatch_session_expired_one_worker_does_not_hang_siblings(
    tmp_path, monkeypatch,
):
    """M15 claude: when w0001 returns session_expired, the dispatcher surfaces
    WorkerSessionExpiredError to the caller in bounded time and leaves no
    half-written outputs that would confuse the validator.

    The dispatcher's docstring documents that siblings cannot honor
    cancellation until their ``subprocess.run`` thread returns; pinning a
    specific outcome for w0002 (file present vs absent) would encode a
    timing race. Instead we pin the *contracts that hold deterministically*:

    1. ``WorkerSessionExpiredError`` propagates.
    2. The dispatch completes within ``timeout_seconds`` (no hang).
    3. w0002 leaves no half-written state — either it never wrote, or both
       its augmented file and its delta file are on disk together.
    """
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "augment_then_consolidate")  # default branch
    # Per-worker overrides: dispatcher writes assignment.json with worker_id,
    # fake_claude reads it and looks up FAKE_CLAUDE_MODE_<WID_UPPER>.
    monkeypatch.setenv("FAKE_CLAUDE_MODE_W0001", "session_expired")
    monkeypatch.setenv("FAKE_CLAUDE_MODE_W0002", "augment")
    n1 = _staged_note(tmp_path, "g", "n1")
    n2 = _staged_note(tmp_path, "g", "n2")
    plan = _plan_with({"w0001": [n1], "w0002": [n2]})

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

    # Either w0002 didn't run yet, or its outputs are coherent — never one
    # without the other (no half-written state). The validator depends on
    # the (augmented, delta) pair being atomic.
    w002_aug = tmp_path / "workers" / "w0002" / "augmented" / "n2.md"
    w002_delta = tmp_path / "workers" / "w0002" / "deltas" / "n2.json"
    assert w002_aug.exists() == w002_delta.exists(), (
        "w0002 wrote one of (augmented, delta) but not the other — "
        "half-written state would confuse the validator. "
        f"aug={w002_aug.exists()} delta={w002_delta.exists()}"
    )
