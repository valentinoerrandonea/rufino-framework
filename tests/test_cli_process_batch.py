"""CLI smoke test for `rufino process-batch`.

Uses --dry-run so no real claude subprocess is launched; we only verify
the wiring (option parsing, runner invocation, exit code, and output
includes the plan path).
"""
from click.testing import CliRunner

from rufino.cli import cli


def test_process_batch_dry_run(
    tmp_path, monkeypatch, batch_adapter, fake_claude_on_path
):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "augment")
    adapter = batch_adapter()
    source = tmp_path / "corpus"
    (source / "math").mkdir(parents=True)
    (source / "math" / "n1.md").write_text("# n\n")
    vault = tmp_path / "vault"

    runner = CliRunner()
    result = runner.invoke(cli, [
        "process-batch", str(source),
        "--adapter", str(adapter),
        "--vault", str(vault),
        "--dry-run",
    ])
    assert result.exit_code == 0, result.output
    assert "plan" in result.output.lower()


def test_process_batch_passes_multimodal_flag(
    tmp_path, monkeypatch, batch_adapter
):
    """The --multimodal flag must reach run_batch as multimodal=True."""
    from unittest.mock import patch, AsyncMock
    from rufino.engine.process.batch.runner import BatchRunResult

    adapter = batch_adapter()
    source = tmp_path / "corpus"
    (source / "math").mkdir(parents=True)
    (source / "math" / "n1.md").write_text("# n\n")
    vault = tmp_path / "vault"

    fake_result = BatchRunResult(
        run_id="r1", dry_run=True, notes_total=0, notes_ok=0,
        notes_failed=0, notes_pending_qa=0, plan_path=tmp_path / "plan.json",
    )
    runner = CliRunner()
    with patch(
        "rufino.cli.run_batch",
        new_callable=AsyncMock, return_value=fake_result,
    ) as mock_run:
        # soffice exists on the dev box; the check is exercised in its own
        # unit test. Here we just want the flag plumbing.
        result = runner.invoke(cli, [
            "process-batch", str(source),
            "--adapter", str(adapter),
            "--vault", str(vault),
            "--dry-run",
            "--multimodal",
        ])
    assert result.exit_code == 0, result.output
    assert mock_run.call_args.kwargs["multimodal"] is True


def test_process_batch_multimodal_defaults_to_false(
    tmp_path, monkeypatch, batch_adapter
):
    from unittest.mock import patch, AsyncMock
    from rufino.engine.process.batch.runner import BatchRunResult

    adapter = batch_adapter()
    source = tmp_path / "corpus"
    (source / "math").mkdir(parents=True)
    (source / "math" / "n1.md").write_text("# n\n")
    vault = tmp_path / "vault"

    fake_result = BatchRunResult(
        run_id="r1", dry_run=True, notes_total=0, notes_ok=0,
        notes_failed=0, notes_pending_qa=0, plan_path=tmp_path / "plan.json",
    )
    runner = CliRunner()
    with patch(
        "rufino.cli.run_batch",
        new_callable=AsyncMock, return_value=fake_result,
    ) as mock_run:
        result = runner.invoke(cli, [
            "process-batch", str(source),
            "--adapter", str(adapter),
            "--vault", str(vault),
            "--dry-run",
        ])
    assert result.exit_code == 0, result.output
    assert mock_run.call_args.kwargs["multimodal"] is False
