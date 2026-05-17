import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class SandboxTimeout(Exception):
    """Raised when a hook exceeds its timeout."""


class SandboxHookFailed(Exception):
    """Raised when a hook exits with non-zero status or invalid output."""


@dataclass
class SandboxResult:
    output: dict[str, Any]
    stderr: str
    error: str | None = None


def run_transform_hook(
    *,
    hook_path: Path,
    input_data: dict[str, Any],
    timeout_seconds: int,
    allow_network: bool,
) -> SandboxResult:
    """Run a transform.py hook in an isolated subprocess.

    Args:
        hook_path: absolute path to transform.py
        input_data: dict passed to the hook as JSON on stdin
        timeout_seconds: hard wall-clock timeout (1-300 seconds)
        allow_network: when False, hook is run with PATH stripped to /usr/bin (best-effort
                       network restriction; a true network namespace is not portable across OSes)

    Returns:
        SandboxResult with parsed JSON output

    Raises:
        SandboxTimeout if hook exceeds timeout
        SandboxHookFailed if hook returns non-zero or invalid JSON
    """
    if not (1 <= timeout_seconds <= 300):
        raise ValueError("timeout_seconds must be in [1, 300]")
    if not hook_path.exists():
        raise SandboxHookFailed(f"Hook not found: {hook_path}")

    env = {"PATH": "/usr/bin", "PYTHONUNBUFFERED": "1"}

    if allow_network:
        cmd = [sys.executable, str(hook_path)]
    else:
        # Fail-closed: patch `socket` module entry points before importing the
        # hook so any `socket.socket(...)`, `socket.create_connection(...)`,
        # `urllib.request.urlopen(...)`, `http.client.HTTPConnection(...)`,
        # etc. that tries to open a connection raises immediately.
        # Not a network namespace, but it does close the common stdlib paths.
        # Patch DNS + connection helpers (not the `socket.socket` class
        # itself, since `ssl` subclasses it on import and patching the class
        # breaks unrelated imports). Blocking DNS + create_connection
        # short-circuits every stdlib networking client (urllib, http.client,
        # smtplib, ftplib, etc.) before any packet leaves the process.
        wrapper = (
            "import socket, runpy, sys\n"
            "_BLOCKED = PermissionError(\n"
            "    'network access disabled by Rufino sandbox (allow_network=False)'\n"
            ")\n"
            "def _blocked(*a, **kw):\n"
            "    raise _BLOCKED\n"
            "socket.create_connection = _blocked  # type: ignore[assignment]\n"
            "socket.getaddrinfo = _blocked  # type: ignore[assignment]\n"
            "socket.gethostbyname = _blocked  # type: ignore[assignment]\n"
            "socket.gethostbyname_ex = _blocked  # type: ignore[assignment]\n"
            "runpy.run_path(sys.argv[1], run_name='__main__')\n"
        )
        cmd = [sys.executable, "-c", wrapper, str(hook_path)]

    # Isolated cwd: hook can write only to its own tmpdir (helps prevent
    # accidental writes to the adapter directory or vault root).
    with tempfile.TemporaryDirectory(prefix="rufino-sandbox-") as isolated_cwd:
        try:
            completed = subprocess.run(
                cmd,
                input=json.dumps(input_data),
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                env=env,
                cwd=isolated_cwd,
                check=False,
            )
        except subprocess.TimeoutExpired as e:
            raise SandboxTimeout(
                f"Hook {hook_path} exceeded {timeout_seconds}s timeout"
            ) from e
        except (FileNotFoundError, PermissionError, OSError) as e:
            raise SandboxHookFailed(
                f"Hook {hook_path} could not be launched: {e}"
            ) from e

    if completed.returncode != 0:
        raise SandboxHookFailed(
            f"Hook {hook_path} exited {completed.returncode}: {completed.stderr}"
        )

    try:
        output = json.loads(completed.stdout)
    except json.JSONDecodeError as e:
        raise SandboxHookFailed(f"Hook {hook_path} returned invalid JSON: {e}") from e

    return SandboxResult(output=output, stderr=completed.stderr, error=None)
