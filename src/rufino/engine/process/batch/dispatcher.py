"""Spawn `claude` worker subprocesses for each WorkerAssignment in a plan.

Workers run via `run_claude` (see runner_helper.py) under an asyncio
semaphore. The fake_claude test fixture mimics the real `claude -p` calling
convention to exercise this code without spending tokens.
"""
import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from rufino.engine.process.batch.errors import (
    DispatchError,
    WorkerSessionExpiredError,
)
from rufino.engine.process.batch.planner import Plan, WorkerAssignment
from rufino.engine.process.batch.runner_helper import (
    ClaudeResult,
    TIMEOUT_EXIT_CODE,
    run_claude,
)


SESSION_EXPIRED_EXIT_CODE = 41


@dataclass(frozen=True)
class WorkerOutcome:
    worker_id: str
    exit_code: int
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True)
class DispatchOutcome:
    workers: tuple[WorkerOutcome, ...] = field(default_factory=tuple)


def build_argv(*, system_prompt: str, staging_dir: Path, vault_slug: str) -> list[str]:
    return [
        "claude",
        "-p",
        "--system-prompt", system_prompt,
        "--allowedTools",
        f"Read,Write,Glob,mcp__ask-rufino-{vault_slug}__*",
        "--cwd", str(staging_dir),
        "--",
        "Procesá las notas listadas en assignment.json siguiendo el system prompt.",
    ]


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
    env = os.environ.copy()
    env["FAKE_CLAUDE_NOTES"] = os.pathsep.join(str(p) for p in assignment.notes)
    env["FAKE_CLAUDE_RUN_ID"] = run_dir.name
    env["FAKE_CLAUDE_WORKER_ID"] = assignment.worker_id

    argv = build_argv(
        system_prompt=system_prompt, staging_dir=staging_dir,
        vault_slug=vault_slug,
    )

    result: ClaudeResult = await run_claude(
        argv=argv, cwd=staging_dir, env=env, timeout_seconds=timeout_seconds,
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
