"""Regression for review-claude I-A: bounded I/O debe ser la ruta productiva.

``run_claude_worker`` implementa streaming bounded capture; ``run_claude``
era una versión blocking que cargaba todo en memoria antes de truncar.
v0.2.1 unifica: ``run_claude`` delega en ``run_claude_worker``.
"""

import asyncio
import inspect
import sys
import textwrap
from pathlib import Path

import pytest

from rufino.engine.process.batch.runner_helper import (
    ClaudeResult,
    MAX_OUTPUT_BYTES,
    run_claude,
)


def test_claude_result_has_truncated_field() -> None:
    """ClaudeResult debe exponer `truncated` para que callers lo logueen."""
    fields = ClaudeResult.__dataclass_fields__
    assert "truncated" in fields
    # Default false para no romper callers viejos.
    assert fields["truncated"].default is False


def test_claude_result_has_timed_out_field() -> None:
    fields = ClaudeResult.__dataclass_fields__
    assert "timed_out" in fields
    assert fields["timed_out"].default is False


def test_run_claude_delegates_to_bounded_worker() -> None:
    """run_claude debe invocar run_claude_worker (bounded streaming)."""
    src = inspect.getsource(run_claude)
    assert "run_claude_worker" in src, (
        "run_claude debe delegar en run_claude_worker para ser bounded "
        "(no cargar todo el stdout/stderr al buffer)."
    )


def test_run_claude_returns_str_payload(tmp_path: Path) -> None:
    """Aunque internamente sea bytes, ClaudeResult sigue siendo str-typed."""
    result = asyncio.run(run_claude(
        argv=[sys.executable, "-c", "print('hello')"],
        cwd=tmp_path,
        env={},
        timeout_seconds=10.0,
    ))
    assert isinstance(result.stdout, str)
    assert result.stdout.strip() == "hello"
    assert result.exit_code == 0
    assert result.truncated is False


def test_run_claude_surfaces_truncation(tmp_path: Path) -> None:
    """Si stdout > MAX_OUTPUT_BYTES, result.truncated debe ser True."""
    # Imprime un payload claramente sobre 1 MB.
    script = textwrap.dedent(f"""
        import sys
        chunk = 'x' * 65536
        for _ in range({MAX_OUTPUT_BYTES // 65536 + 4}):
            sys.stdout.write(chunk)
        sys.stdout.flush()
    """)
    result = asyncio.run(run_claude(
        argv=[sys.executable, "-c", script],
        cwd=tmp_path,
        env={},
        timeout_seconds=30.0,
    ))
    assert result.exit_code == 0
    assert result.truncated is True
    # Y el payload queda capeado.
    assert len(result.stdout.encode("utf-8")) <= MAX_OUTPUT_BYTES


def test_run_claude_timeout_surfaces_timed_out(tmp_path: Path) -> None:
    """Timeout vuelve result.exit_code=124 y timed_out=True."""
    result = asyncio.run(run_claude(
        argv=[sys.executable, "-c", "import time; time.sleep(5)"],
        cwd=tmp_path,
        env={},
        timeout_seconds=0.2,
    ))
    assert result.exit_code == 124
    assert result.timed_out is True
