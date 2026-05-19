"""Spawn `claude` worker subprocesses for each WorkerAssignment in a plan.

Workers run via `run_claude` (see runner_helper.py) under an asyncio
semaphore. The fake_claude test fixture mimics the real `claude -p` calling
convention to exercise this code without spending tokens.
"""
import asyncio
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from rufino.engine.process.batch.errors import WorkerSessionExpiredError
from rufino.engine.process.batch.planner import Plan, WorkerAssignment
from rufino.engine.process.batch.runner_helper import ClaudeResult, run_claude


SESSION_EXPIRED_EXIT_CODE = 41

# Final positional argument passed to `claude -p`. The system prompt carries
# all the instructions; this string just nudges the worker to start. Kept as
# a constant so retry.py can pass the exact same kickoff and tests can grep
# for a single source of truth.
_WORKER_KICKOFF = "Procesá las notas listadas en assignment.json siguiendo el system prompt."


@dataclass(frozen=True)
class WorkerOutcome:
    worker_id: str
    exit_code: int
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True)
class DispatchOutcome:
    workers: tuple[WorkerOutcome, ...] = field(default_factory=tuple)


def build_argv(*, system_prompt: str, vault_slug: str) -> list[str]:
    return [
        "claude",
        "-p",
        "--system-prompt", system_prompt,
        "--allowedTools",
        f"Read,Write,Glob,mcp__ask-rufino-{vault_slug}__*",
        "--",
        _WORKER_KICKOFF,
    ]


def _write_assignment(staging_dir: Path, assignment: WorkerAssignment, run_id: str) -> None:
    payload = {
        "run_id": run_id,
        "worker_id": assignment.worker_id,
        "group": assignment.group,
        "notes": [str(p) for p in assignment.notes],
    }
    (staging_dir / "assignment.json").write_text(json.dumps(payload, indent=2))


async def _run_one(
    assignment: WorkerAssignment,
    *,
    run_dir: Path,
    system_prompt: str,
    vault_slug: str,
    timeout_seconds: float,
) -> WorkerOutcome:
    staging_dir = run_dir / "workers" / assignment.worker_id
    staging_dir.mkdir(parents=True, exist_ok=True)
    _write_assignment(staging_dir, assignment, run_id=run_dir.name)

    argv = build_argv(system_prompt=system_prompt, vault_slug=vault_slug)

    result: ClaudeResult = await run_claude(
        argv=argv,
        cwd=staging_dir,
        env=os.environ.copy(),
        timeout_seconds=timeout_seconds,
    )

    if result.exit_code == SESSION_EXPIRED_EXIT_CODE:
        raise WorkerSessionExpiredError(
            "Tu sesión Claude está expirada. Corré `claude login` y reintentá."
        )

    return WorkerOutcome(
        worker_id=assignment.worker_id,
        exit_code=result.exit_code,
        stdout=result.stdout, stderr=result.stderr,
    )


async def dispatch(
    *,
    plan: Plan,
    run_dir: Path,
    system_prompt_for: Callable[[WorkerAssignment], str],
    vault_slug: str,
    max_workers: int,
    timeout_seconds: float = 300.0,
) -> DispatchOutcome:
    """Run all workers in plan.workers, bounded by max_workers concurrent.

    Raises WorkerSessionExpiredError immediately if any worker reports an
    expired session. Other failures (timeouts, non-zero exits, empty outputs)
    are reflected in WorkerOutcome and left for the validator.

    Note on cancellation: when a worker raises WorkerSessionExpiredError,
    asyncio.gather cancels the sibling tasks, but workers blocked inside
    asyncio.to_thread → subprocess.run cannot honor cancellation until their
    subprocess returns. In practice the call hangs until the slowest in-flight
    worker hits its own timeout. Acceptable for v0.1.0 — caller sees the
    session error and reruns once `claude login` is fixed.
    """
    if not plan.workers:
        return DispatchOutcome(workers=())

    sem = asyncio.Semaphore(max(1, max_workers))

    async def _guarded(a: WorkerAssignment) -> WorkerOutcome:
        async with sem:
            return await _run_one(
                a, run_dir=run_dir,
                system_prompt=system_prompt_for(a),
                vault_slug=vault_slug,
                timeout_seconds=timeout_seconds,
            )

    outcomes = await asyncio.gather(*(_guarded(a) for a in plan.workers))
    return DispatchOutcome(workers=tuple(outcomes))
