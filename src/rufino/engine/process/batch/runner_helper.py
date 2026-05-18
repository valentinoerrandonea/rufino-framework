"""Single chokepoint for invoking the `claude` binary.

We use `subprocess.run` with argv passed as a list (no shell, no injection
surface) and wrap it in `asyncio.to_thread` so callers can fan many workers
out under an asyncio.Semaphore without giving up async scheduling.

This is the only module that talks to subprocess.run for `claude` —
everything else calls run_claude().
"""
import asyncio
import subprocess
from dataclasses import dataclass
from pathlib import Path


TIMEOUT_EXIT_CODE = 124


@dataclass(frozen=True)
class ClaudeResult:
    exit_code: int
    stdout: str = ""
    stderr: str = ""


def _run_blocking(
    argv: list[str], cwd: Path, env: dict[str, str], timeout_seconds: float,
) -> ClaudeResult:
    try:
        completed = subprocess.run(
            argv,
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        return ClaudeResult(
            exit_code=TIMEOUT_EXIT_CODE,
            stderr=f"timed out after {timeout_seconds}s: {e}",
        )
    return ClaudeResult(
        exit_code=completed.returncode,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
    )


async def run_claude(
    *,
    argv: list[str],
    cwd: Path,
    env: dict[str, str],
    timeout_seconds: float,
) -> ClaudeResult:
    """Run a claude subprocess to completion. Returns ClaudeResult always —
    callers inspect exit_code for non-zero / timeout (124) / auth-fail (41).
    """
    return await asyncio.to_thread(
        _run_blocking, argv, cwd, env, timeout_seconds,
    )
