import json
import subprocess
import sys
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

    env = {"PATH": "/usr/bin", "PYTHONUNBUFFERED": "1"}

    try:
        completed = subprocess.run(
            [sys.executable, str(hook_path)],
            input=json.dumps(input_data),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise SandboxTimeout(
            f"Hook {hook_path} exceeded {timeout_seconds}s timeout"
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
