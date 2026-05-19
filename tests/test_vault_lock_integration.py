"""Integration: run_batch and resume_pending_qa must acquire the vault lock.

Two concurrent process-batch (or qa-poll) invocations against the same vault
would stomp on each other's run dirs. v0.2 wraps both entry points in
``vault_lock(wait=False)`` so the second caller fails fast with BatchError.
"""
import asyncio
import multiprocessing
import time
from pathlib import Path

import pytest

from rufino.engine.process.batch.errors import BatchError
from rufino.engine.process.batch.runner import run_batch
from rufino.engine.process.batch.qa_resume import resume_pending_qa
from rufino.runtime.vault_lock import vault_lock


def _hold_lock(vault: str, seconds: float) -> None:
    with vault_lock(Path(vault)):
        time.sleep(seconds)


def test_run_batch_fails_when_vault_locked(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    adapter_dir = tmp_path / "adapter"
    adapter_dir.mkdir()
    source = tmp_path / "src"
    source.mkdir()

    holder = multiprocessing.Process(target=_hold_lock, args=(str(vault), 1.5))
    holder.start()
    try:
        time.sleep(0.3)
        with pytest.raises(BatchError, match="locked"):
            asyncio.run(run_batch(
                source=source, adapter_dir=adapter_dir, vault_root=vault,
                workers=1, batch_size=1, dry_run=True,
            ))
    finally:
        holder.join()


def test_resume_pending_qa_fails_when_vault_locked(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    question_file = vault / "questions" / "q.md"
    question_file.parent.mkdir(parents=True)
    question_file.write_text("---\nanswer: x\norigin: process-batch\n---\n", encoding="utf-8")

    holder = multiprocessing.Process(target=_hold_lock, args=(str(vault), 1.5))
    holder.start()
    try:
        time.sleep(0.3)
        with pytest.raises(BatchError, match="locked"):
            asyncio.run(resume_pending_qa(
                vault_root=vault, question_file=question_file,
            ))
    finally:
        holder.join()
