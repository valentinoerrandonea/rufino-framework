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


def test_process_batch_passes_timeout(tmp_path, monkeypatch, batch_adapter):
    """--timeout must reach run_batch as timeout_seconds (float)."""
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
            "--timeout", "900",
        ])
    assert result.exit_code == 0, result.output
    assert mock_run.call_args.kwargs["timeout_seconds"] == 900.0


def test_process_batch_model_defaults_to_sonnet(
    tmp_path, monkeypatch, batch_adapter
):
    """Without --model the runner gets sonnet — the fast default that keeps
    per-note augmentation from inheriting the slow interactive Opus."""
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
    assert mock_run.call_args.kwargs["model"] == "sonnet"


def test_process_batch_model_override(tmp_path, monkeypatch, batch_adapter):
    """--model must reach run_batch verbatim."""
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
            "--model", "opus",
        ])
    assert result.exit_code == 0, result.output
    assert mock_run.call_args.kwargs["model"] == "opus"


def test_process_batch_timeout_defaults_to_900(
    tmp_path, monkeypatch, batch_adapter
):
    """Without --timeout the runner gets the generous 900s (15 min) default,
    so dense notes don't depend on the retry path to survive."""
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
    assert mock_run.call_args.kwargs["timeout_seconds"] == 900.0


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


def test_process_batch_multimodal_fails_fast_without_soffice(
    tmp_path, monkeypatch, batch_adapter
):
    """When --multimodal is set but soffice is absent, the CLI must exit 127
    before touching the runner — fail-fast, not mid-batch."""
    from unittest.mock import patch, AsyncMock

    monkeypatch.setattr(
        "rufino.runtime.prereq_checker.shutil.which", lambda name: None,
    )

    adapter = batch_adapter()
    source = tmp_path / "corpus"
    (source / "math").mkdir(parents=True)
    (source / "math" / "n1.md").write_text("# n\n")
    vault = tmp_path / "vault"

    runner = CliRunner()
    with patch(
        "rufino.cli.run_batch",
        new_callable=AsyncMock,
    ) as mock_run:
        result = runner.invoke(cli, [
            "process-batch", str(source),
            "--adapter", str(adapter),
            "--vault", str(vault),
            "--dry-run",
            "--multimodal",
        ])

    assert result.exit_code == 127, result.output
    assert "libreoffice" in result.output.lower() or "brew install" in result.output.lower()
    mock_run.assert_not_called()


def test_process_batch_multimodal_proceeds_when_soffice_present(
    tmp_path, monkeypatch, batch_adapter,
):
    """Positive case paired with the negative: confirms the patch target
    is the real one used by the prereq check. If a refactor changes the
    import style and the negative test silently no-ops (real soffice on
    PATH), this positive test detects the drift."""
    from unittest.mock import patch, AsyncMock

    monkeypatch.setattr(
        "rufino.runtime.prereq_checker.shutil.which",
        lambda name: "/fake/soffice" if name == "soffice" else None,
    )

    adapter = batch_adapter()
    source = tmp_path / "corpus"
    (source / "math").mkdir(parents=True)
    (source / "math" / "n1.md").write_text("# n\n")
    vault = tmp_path / "vault"

    runner = CliRunner()
    with patch(
        "rufino.cli.run_batch",
        new_callable=AsyncMock,
    ) as mock_run:
        mock_run.return_value.dry_run = True
        mock_run.return_value.plan_path = vault / "plan.json"
        mock_run.return_value.notes_total = 1
        result = runner.invoke(cli, [
            "process-batch", str(source),
            "--adapter", str(adapter),
            "--vault", str(vault),
            "--dry-run",
            "--multimodal",
        ])
    assert result.exit_code == 0, result.output
    mock_run.assert_called_once()


def test_process_batch_cli_summary_omits_optional_fields_when_zero(
    tmp_path, monkeypatch, batch_adapter,
):
    """The summary line must NOT include skipped_stage / below_compression_floor
    when those counters are zero — keeps the common-case output noise-free."""
    from unittest.mock import patch, AsyncMock
    from rufino.engine.process.batch.runner import BatchRunResult

    adapter = batch_adapter()
    source = tmp_path / "corpus"
    (source / "math").mkdir(parents=True)
    (source / "math" / "n1.md").write_text("# n\n")
    vault = tmp_path / "vault"

    runner = CliRunner()
    with patch("rufino.cli.run_batch", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = BatchRunResult(
            run_id="r1", dry_run=False,
            notes_total=1, notes_ok=1, notes_failed=0, notes_pending_qa=0,
            notes_skipped_stage=0, notes_below_compression_floor=0,
        )
        result = runner.invoke(cli, [
            "process-batch", str(source),
            "--adapter", str(adapter), "--vault", str(vault),
        ])
    assert result.exit_code == 0
    assert "skipped_stage" not in result.output
    assert "below_compression_floor" not in result.output


def test_process_batch_cli_summary_surfaces_below_compression_floor(
    tmp_path, monkeypatch, batch_adapter,
):
    from unittest.mock import patch, AsyncMock
    from rufino.engine.process.batch.runner import BatchRunResult

    adapter = batch_adapter()
    source = tmp_path / "corpus"
    (source / "math").mkdir(parents=True)
    (source / "math" / "n1.md").write_text("# n\n")
    vault = tmp_path / "vault"

    runner = CliRunner()
    with patch("rufino.cli.run_batch", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = BatchRunResult(
            run_id="r1", dry_run=False,
            notes_total=10, notes_ok=10, notes_failed=0, notes_pending_qa=0,
            notes_skipped_stage=0,
            notes_below_compression_floor=4, compression_floor=0.9,
        )
        result = runner.invoke(cli, [
            "process-batch", str(source),
            "--adapter", str(adapter), "--vault", str(vault),
        ])
    assert "below_compression_floor=4" in result.output
    assert "floor=0.9" in result.output
