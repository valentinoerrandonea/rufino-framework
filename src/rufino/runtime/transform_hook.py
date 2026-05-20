"""Subprocess sandbox for adapter ``transform_hook`` scripts.

Used by Ingest and Process workers (Task 4.2) to invoke a user-supplied
``transform.py`` script. The contract is intentionally narrow:

* Input dict is serialized to JSON and piped to the hook on stdin.
* Hook is expected to print a JSON object on stdout.
* Failures (timeout, non-zero exit, malformed output) raise
  :class:`TransformHookError`. Callers treat these as warnings — the v0.2
  spec says a misbehaving hook must never abort the worker.

Non-JSON-native values in ``input_dict`` (e.g., ``datetime.date``) are
coerced to strings via ``default=str`` so PyYAML scalars like
``created: 2026-05-19`` don't raise ``TypeError`` mid-batch.

Defense-in-depth (network block, fs sandbox) is out of scope for this
primitive — that lives in :mod:`rufino.runtime.sandbox`, which the worker
may opt into separately.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


class TransformHookError(RuntimeError):
    """Raised when a transform_hook fails (timeout, bad exit, malformed output)."""


def run_transform_hook(
    script_path: Path,
    input_dict: dict[str, Any],
    *,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Run a Python transform_hook in subprocess sandbox.

    Input via stdin (JSON), output via stdout (JSON). Raises
    :class:`TransformHookError` on timeout, non-zero exit, or malformed
    output. Caller treats those as warnings (no abort) per the spec.

    Args:
        script_path: Absolute path to the hook script. Invoked with
            ``sys.executable`` so it runs under the same interpreter as
            Rufino itself.
        input_dict: Payload handed to the hook on stdin (JSON-encoded
            UTF-8).
        timeout: Hard wall-clock timeout in seconds.

    Returns:
        The parsed JSON object the hook printed on stdout.

    Raises:
        TransformHookError: timeout, non-zero exit, or malformed stdout.
    """
    # default=str coerces non-JSON-native YAML scalars (datetime.date, sets,
    # tuples, etc.) to their string repr. Without it, a Process note whose
    # frontmatter contains `created: 2026-05-19` would crash mid-batch with
    # TypeError — not caught by the (OSError, UnicodeDecodeError,
    # FrontmatterError) guard around the call site.
    payload = json.dumps(input_dict, default=str).encode("utf-8")
    try:
        # TODO(v0.2.x): capture_output is unbounded — a misbehaving hook could OOM the worker.
        # Mirror the bounded-read pattern in engine/process/batch/runner_helper.py once stabilized.
        result = subprocess.run(
            [sys.executable, str(script_path)],
            input=payload,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise TransformHookError(
            f"transform_hook {script_path} timeout"
        ) from e

    if result.returncode != 0:
        stderr_excerpt = result.stderr.decode("utf-8", errors="replace")[:500]
        raise TransformHookError(
            f"transform_hook {script_path} exited {result.returncode}: "
            f"{stderr_excerpt}"
        )

    try:
        out = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise TransformHookError(
            f"transform_hook {script_path} malformed JSON: {e}"
        ) from e

    if not isinstance(out, dict):
        raise TransformHookError(
            f"transform_hook {script_path} returned non-dict JSON: "
            f"{type(out).__name__}"
        )
    return out
