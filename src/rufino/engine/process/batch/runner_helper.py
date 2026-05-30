"""Single chokepoint for invoking the `claude` binary.

We use ``asyncio.create_subprocess_exec`` (argv list, no shell, no injection
surface) and read stdout/stderr concurrently with a per-stream byte cap so a
runaway worker can't OOM the parent. Callers see a :class:`ClaudeResult`
with strings already decoded, the exit code, plus ``truncated`` and
``timed_out`` flags they can surface in logs.
"""
import asyncio
from dataclasses import dataclass
from pathlib import Path


TIMEOUT_EXIT_CODE = 124
# Cap per-stream capture to keep a runaway worker from OOM'ing the parent.
MAX_OUTPUT_BYTES = 1_000_000

# Markers Claude Code sets in its own environment. The nested-session guard in
# the `claude` binary aborts (exit 1) if it sees CLAUDECODE, which breaks
# `rufino process-batch` when launched from inside a Claude Code session. We
# strip both before spawning the worker so the child starts a clean session.
_NESTED_SESSION_ENV_KEYS = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")


@dataclass(frozen=True)
class ClaudeResult:
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    truncated: bool = False
    timed_out: bool = False


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


async def run_claude(
    *,
    argv: list[str],
    cwd: Path,
    env: dict[str, str],
    timeout_seconds: float,
) -> ClaudeResult:
    """Run a claude subprocess to completion via the bounded worker.

    Delegates to :func:`run_claude_worker` so production callers also get
    streaming-bounded I/O (~1 MB cap per stream). Returns a
    :class:`ClaudeResult` — callers inspect ``exit_code`` for non-zero /
    timeout (124) / auth-fail (41), and ``truncated`` to surface logging.

    Strips nested-session markers (``CLAUDECODE`` & co.) from the env so the
    worker `claude` doesn't abort when rufino itself runs inside Claude Code.
    """
    child_env = {
        k: v for k, v in env.items() if k not in _NESTED_SESSION_ENV_KEYS
    }
    worker = await run_claude_worker(
        cmd=argv, cwd=cwd, timeout=timeout_seconds, env=child_env,
    )
    if worker.timed_out:
        return ClaudeResult(
            exit_code=TIMEOUT_EXIT_CODE,
            stdout="",
            stderr=f"timed out after {timeout_seconds}s",
            truncated=False,
            timed_out=True,
        )
    return ClaudeResult(
        exit_code=worker.returncode,
        stdout=worker.stdout.decode("utf-8", errors="replace"),
        stderr=worker.stderr.decode("utf-8", errors="replace"),
        truncated=worker.truncated,
    )
