"""Tests for the `rufino process --mode full` single-note wrapper.

The wrapper stages the note into a tempdir-of-one and delegates to
``run_batch`` with ``workers=1, batch_size=1``. The tests below monkeypatch
``rufino.cli.run_batch`` to control its return value (or raise) without
spawning a real ``claude`` subprocess.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

import rufino.cli as cli_module
from rufino.cli import cli
from rufino.engine.process.batch.errors import BatchError, WorkerSessionExpiredError
from rufino.engine.process.batch.runner import BatchRunResult


def _make_note(tmp_path: Path) -> Path:
    note = tmp_path / "n.md"
    note.write_text("# n\nbody\n", encoding="utf-8")
    return note


def _make_adapter(tmp_path: Path) -> Path:
    adapter = tmp_path / "adapter"
    adapter.mkdir()
    # Empty marker file; real parsing happens inside run_batch, which we mock.
    (adapter / "manifest.yaml").write_text("adapter_name: x\n", encoding="utf-8")
    return adapter


def _patch_run_batch(monkeypatch, result_or_exc):
    """Replace ``rufino.cli.run_batch`` with an async fn returning a value
    or raising. ``result_or_exc`` is either a BatchRunResult or an Exception."""

    async def fake(**kwargs):
        if isinstance(result_or_exc, BaseException):
            raise result_or_exc
        return result_or_exc

    monkeypatch.setattr(cli_module, "run_batch", fake)


def test_full_happy_path_exits_zero(tmp_path, monkeypatch):
    note = _make_note(tmp_path)
    adapter = _make_adapter(tmp_path)
    vault = tmp_path / "vault"
    vault.mkdir()

    _patch_run_batch(monkeypatch, BatchRunResult(
        run_id="r1", dry_run=False, notes_total=1,
        notes_ok=1, notes_failed=0, notes_pending_qa=0,
    ))

    runner = CliRunner()
    result = runner.invoke(cli, [
        "process", str(note),
        "--vault", str(vault),
        "--mode", "full",
        "--adapter-dir", str(adapter),
    ])
    assert result.exit_code == 0, result.output
    assert note.name in result.output


def test_full_pending_qa_exits_three(tmp_path, monkeypatch):
    note = _make_note(tmp_path)
    adapter = _make_adapter(tmp_path)
    vault = tmp_path / "vault"
    vault.mkdir()

    _patch_run_batch(monkeypatch, BatchRunResult(
        run_id="r2", dry_run=False, notes_total=1,
        notes_ok=0, notes_failed=0, notes_pending_qa=1,
    ))

    runner = CliRunner()
    result = runner.invoke(cli, [
        "process", str(note),
        "--vault", str(vault),
        "--mode", "full",
        "--adapter-dir", str(adapter),
    ])
    assert result.exit_code == 3, result.output
    assert "r2" in result.output
    assert note.name in result.output


def test_full_failed_exits_one(tmp_path, monkeypatch):
    note = _make_note(tmp_path)
    adapter = _make_adapter(tmp_path)
    vault = tmp_path / "vault"
    vault.mkdir()

    _patch_run_batch(monkeypatch, BatchRunResult(
        run_id="r3", dry_run=False, notes_total=1,
        notes_ok=0, notes_failed=1, notes_pending_qa=0,
    ))

    runner = CliRunner()
    result = runner.invoke(cli, [
        "process", str(note),
        "--vault", str(vault),
        "--mode", "full",
        "--adapter-dir", str(adapter),
    ])
    assert result.exit_code == 1, result.output
    # Error message should land on stderr; CliRunner mixes them into .output
    # by default. Assert on the combined buffer.
    assert "r3" in result.output
    assert note.name in result.output


def test_full_missing_claude_exits_127(tmp_path, monkeypatch):
    note = _make_note(tmp_path)
    adapter = _make_adapter(tmp_path)
    vault = tmp_path / "vault"
    vault.mkdir()

    fnf = FileNotFoundError("claude not found")
    fnf.filename = "claude"
    _patch_run_batch(monkeypatch, fnf)

    runner = CliRunner()
    result = runner.invoke(cli, [
        "process", str(note),
        "--vault", str(vault),
        "--mode", "full",
        "--adapter-dir", str(adapter),
    ])
    assert result.exit_code == 127, result.output


def test_full_batch_error_exits_one(tmp_path, monkeypatch):
    note = _make_note(tmp_path)
    adapter = _make_adapter(tmp_path)
    vault = tmp_path / "vault"
    vault.mkdir()

    _patch_run_batch(monkeypatch, BatchError("boom"))

    runner = CliRunner()
    result = runner.invoke(cli, [
        "process", str(note),
        "--vault", str(vault),
        "--mode", "full",
        "--adapter-dir", str(adapter),
    ])
    assert result.exit_code == 1, result.output
    assert "boom" in result.output


def test_full_worker_session_expired_exits_one(tmp_path, monkeypatch):
    note = _make_note(tmp_path)
    adapter = _make_adapter(tmp_path)
    vault = tmp_path / "vault"
    vault.mkdir()

    _patch_run_batch(monkeypatch, WorkerSessionExpiredError("session expired"))

    runner = CliRunner()
    result = runner.invoke(cli, [
        "process", str(note),
        "--vault", str(vault),
        "--mode", "full",
        "--adapter-dir", str(adapter),
    ])
    assert result.exit_code == 1, result.output


def test_full_requires_adapter_dir(tmp_path):
    note = _make_note(tmp_path)
    vault = tmp_path / "vault"
    vault.mkdir()

    runner = CliRunner()
    result = runner.invoke(cli, [
        "process", str(note),
        "--vault", str(vault),
        "--mode", "full",
    ])
    assert result.exit_code == 1, result.output
    assert "--adapter-dir" in result.output


def test_full_passes_workers_and_batch_size_of_one(tmp_path, monkeypatch):
    """The wrapper hardcodes workers=1, batch_size=1, dry_run=False, and
    points run_batch at a tempdir containing exactly the requested note."""
    note = _make_note(tmp_path)
    adapter = _make_adapter(tmp_path)
    vault = tmp_path / "vault"
    vault.mkdir()

    captured: dict = {}

    async def spy(**kwargs):
        captured.update(kwargs)
        # Snapshot of the staging dir before run_batch returns; the wrapper's
        # TemporaryDirectory unwinds on exit, so we copy contents now.
        source = Path(kwargs["source"])
        captured["staged_files"] = sorted(p.name for p in source.iterdir())
        return BatchRunResult(
            run_id="rX", dry_run=False, notes_total=1,
            notes_ok=1, notes_failed=0, notes_pending_qa=0,
        )

    monkeypatch.setattr(cli_module, "run_batch", spy)

    runner = CliRunner()
    result = runner.invoke(cli, [
        "process", str(note),
        "--vault", str(vault),
        "--mode", "full",
        "--adapter-dir", str(adapter),
    ])
    assert result.exit_code == 0, result.output
    assert captured["workers"] == 1
    assert captured["batch_size"] == 1
    assert captured["dry_run"] is False
    assert captured["adapter_dir"] == adapter
    assert captured["vault_root"] == vault
    assert captured["staged_files"] == [note.name]
