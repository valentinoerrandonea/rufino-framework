"""Bounded stdout/stderr capture for claude worker subprocesses.

A misbehaving worker could write unlimited output and OOM the parent. v0.2
caps each stream at ``MAX_OUTPUT_BYTES`` and signals truncation via
``WorkerResult.truncated``.
"""
import asyncio
from pathlib import Path

from rufino.engine.process.batch.runner_helper import (
    MAX_OUTPUT_BYTES,
    run_claude_worker,
)


def test_output_truncated_above_max(tmp_path: Path) -> None:
    fake = tmp_path / "claude"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "sys.stdout.write('A' * 2_000_000)\n"
        "sys.exit(0)\n"
    )
    fake.chmod(0o755)
    result = asyncio.run(
        run_claude_worker(cmd=[str(fake)], cwd=tmp_path, timeout=10.0)
    )
    assert len(result.stdout) <= MAX_OUTPUT_BYTES
    assert result.truncated is True
    assert result.returncode == 0


def test_output_under_cap_not_truncated(tmp_path: Path) -> None:
    fake = tmp_path / "claude"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "sys.stdout.write('hola')\n"
        "sys.exit(0)\n"
    )
    fake.chmod(0o755)
    result = asyncio.run(
        run_claude_worker(cmd=[str(fake)], cwd=tmp_path, timeout=10.0)
    )
    assert result.stdout == b"hola"
    assert result.truncated is False
    assert result.timed_out is False


def test_stderr_truncated_above_max(tmp_path: Path) -> None:
    fake = tmp_path / "claude"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "sys.stderr.write('E' * 2_000_000)\n"
        "sys.exit(0)\n"
    )
    fake.chmod(0o755)
    result = asyncio.run(
        run_claude_worker(cmd=[str(fake)], cwd=tmp_path, timeout=10.0)
    )
    assert len(result.stderr) <= MAX_OUTPUT_BYTES
    assert result.truncated is True
    assert result.returncode == 0


def test_worker_timeout(tmp_path: Path) -> None:
    fake = tmp_path / "claude"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import time\n"
        "time.sleep(5)\n"
    )
    fake.chmod(0o755)
    result = asyncio.run(
        run_claude_worker(cmd=[str(fake)], cwd=tmp_path, timeout=0.5)
    )
    assert result.timed_out is True
    assert result.returncode == -1
