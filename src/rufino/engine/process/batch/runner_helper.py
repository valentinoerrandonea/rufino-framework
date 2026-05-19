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
# Cap per-stream capture to keep a runaway worker from OOM'ing the parent.
MAX_OUTPUT_BYTES = 1_000_000


@dataclass(frozen=True)
class ClaudeResult:
    exit_code: int
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True)
class WorkerResult:
    """Bounded-capture result of a worker subprocess invocation."""
    returncode: int
    stdout: bytes
    stderr: bytes
    truncated: bool = False
    timed_out: bool = False


async def _read_bounded(
    stream: asyncio.StreamReader, cap: int,
) -> tuple[bytes, bool]:
    buf = bytearray()
    truncated = False
    while True:
        chunk = await stream.read(4096)
        if not chunk:
            break
        if len(buf) + len(chunk) > cap:
            buf.extend(chunk[: cap - len(buf)])
            truncated = True
            while await stream.read(4096):
                pass
            break
        buf.extend(chunk)
    return bytes(buf), truncated


async def run_claude_worker(
    *,
    cmd: list[str],
    cwd: Path,
    timeout: float,
    env: dict[str, str] | None = None,
) -> WorkerResult:
    """Run a worker subprocess with bounded stdout/stderr capture.

    Caps each stream at ``MAX_OUTPUT_BYTES``; on overflow, the rest is
    discarded and ``truncated=True``. On timeout, the child is killed and
    ``timed_out=True`` with ``returncode=-1``. Uses argv list (no shell).
    """
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(cwd),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        async def _collect() -> tuple[bytes, bool, bytes, bool]:
            # Read both streams concurrently. Reading sequentially would
            # deadlock when the child fills the OS pipe buffer of whichever
            # stream we are NOT yet draining (~16-64KB on macOS) — the child
            # blocks on write(), we block on read() of the other stream.
            (out, out_trunc), (err, err_trunc) = await asyncio.gather(
                _read_bounded(proc.stdout, MAX_OUTPUT_BYTES),
                _read_bounded(proc.stderr, MAX_OUTPUT_BYTES),
            )
            await proc.wait()
            return out, out_trunc, err, err_trunc

        out, out_trunc, err, err_trunc = await asyncio.wait_for(
            _collect(), timeout=timeout,
        )
        return WorkerResult(
            returncode=proc.returncode if proc.returncode is not None else -1,
            stdout=out,
            stderr=err,
            truncated=out_trunc or err_trunc,
        )
    except asyncio.TimeoutError:
        proc.kill()
        try:
            await proc.wait()
        except Exception:
            pass
        return WorkerResult(
            returncode=-1, stdout=b"", stderr=b"",
            truncated=False, timed_out=True,
        )


def _truncate_utf8(s: str, cap: int) -> str:
    raw = s.encode("utf-8", errors="replace")
    if len(raw) <= cap:
        return s
    return raw[:cap].decode("utf-8", errors="replace")


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
        stdout=_truncate_utf8(completed.stdout or "", MAX_OUTPUT_BYTES),
        stderr=_truncate_utf8(completed.stderr or "", MAX_OUTPUT_BYTES),
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
