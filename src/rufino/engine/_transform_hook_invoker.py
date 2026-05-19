"""Shared invocation helper for adapter ``transform_hook`` scripts.

Used by both Ingest (``engine/ingest/runner.py``) and Process
(``engine/process/batch/runner.py``) to call a user-supplied hook between
fetch/LLM and the final write. Failures degrade gracefully (warn + return
the original record); the v0.2 spec says a misbehaving hook must never
abort a worker.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from rufino.runtime.transform_hook import TransformHookError, run_transform_hook


log = logging.getLogger(__name__)


def _maybe_apply_transform_hook(
    hook_path: Path | None,
    record: dict[str, Any],
    *,
    adapter_dir: Path,
) -> dict[str, Any]:
    """Apply transform_hook if configured; on failure, log + return original.

    Args:
        hook_path: Relative path from the adapter dir (e.g. ``./transform.py``)
            or ``None`` if the adapter does not declare a hook.
        record: Dict to feed the hook on stdin.
        adapter_dir: Adapter directory used to resolve ``hook_path``.

    Returns:
        Either the hook's mutated dict, or ``record`` unchanged when the
        hook is unconfigured / missing on disk / errored.
    """
    if hook_path is None:
        return record
    adapter_root = adapter_dir.resolve()
    resolved = (adapter_dir / hook_path).resolve()
    # Refuse path traversal: hook must live inside adapter_dir. Absolute
    # paths trivially fail this check (they resolve outside adapter_root).
    if not resolved.is_relative_to(adapter_root):
        log.warning(
            "transform_hook %s escapes adapter_dir %s; skipping",
            hook_path, adapter_root,
        )
        return record
    if not resolved.exists():
        log.warning("transform_hook %s does not exist; skipping", resolved)
        return record
    try:
        return run_transform_hook(resolved, record)
    except TransformHookError as e:
        log.warning(
            "transform_hook %s failed (graceful degrade): %s", resolved, e,
        )
        return record
