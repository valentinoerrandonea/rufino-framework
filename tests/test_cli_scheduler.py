"""Tests for `rufino install-ingest` / `uninstall-ingest` / `list-ingests`."""

from pathlib import Path

import yaml
from click.testing import CliRunner

from rufino.cli import cli


class FakeBackend:
    def __init__(self) -> None:
        self.installs: list[dict] = []
        self.uninstalls: list[str] = []
        self.jobs: list[str] = []

    def install(self, *, job_id, schedule, cmd, log_path):
        self.installs.append(
            dict(job_id=job_id, schedule=schedule, cmd=cmd, log_path=log_path)
        )
        if job_id not in self.jobs:
            self.jobs.append(job_id)

    def uninstall(self, *, job_id):
        self.uninstalls.append(job_id)
        if job_id in self.jobs:
            self.jobs.remove(job_id)

    def list_jobs(self):
        return list(self.jobs)


def _write_adapter(adapter_dir: Path, manifest: dict) -> None:
    adapter_dir.mkdir(parents=True)
    (adapter_dir / "manifest.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
    )


def _base_manifest():
    return {
        "adapter_name": "drive-facultad",
        "source_name": "gdrive",
        "schedule": "0 22 * * *",
        "output_mode": "import_raw",
        "auth": {"type": "oauth2"},
        "target_inbox": "inbox/cufona/",
        "process_with": "apunte-clase",
        "trigger": "immediate",
    }


def test_install_ingest_invokes_backend(tmp_path: Path, monkeypatch) -> None:
    adapter_dir = tmp_path / "adapter"
    _write_adapter(adapter_dir, _base_manifest())
    vault = tmp_path / "vault"
    vault.mkdir()
    rufino_home = tmp_path / "rufino-home"

    fake = FakeBackend()
    monkeypatch.setattr("rufino.cli._scheduler_backend", lambda: fake)

    runner = CliRunner()
    result = runner.invoke(cli, [
        "install-ingest", str(adapter_dir),
        "--vault", str(vault),
        "--rufino-home", str(rufino_home),
    ])
    assert result.exit_code == 0, result.output
    assert len(fake.installs) == 1
    call = fake.installs[0]
    assert call["schedule"] == "0 22 * * *"
    assert call["job_id"].startswith("rufino-ingest-")
    assert "drive-facultad" in call["job_id"]
    assert str(adapter_dir) in call["cmd"]
    assert str(vault) in call["cmd"]
    assert call["log_path"].startswith(str(rufino_home / "logs"))
    assert (rufino_home / "logs").exists()


def test_install_ingest_fails_on_missing_manifest(tmp_path: Path, monkeypatch) -> None:
    adapter_dir = tmp_path / "empty-adapter"
    adapter_dir.mkdir()
    vault = tmp_path / "vault"
    vault.mkdir()

    monkeypatch.setattr("rufino.cli._scheduler_backend", lambda: FakeBackend())

    runner = CliRunner()
    result = runner.invoke(cli, [
        "install-ingest", str(adapter_dir),
        "--vault", str(vault),
    ])
    assert result.exit_code != 0
    assert "manifest" in result.output.lower()


def test_install_ingest_fails_on_invalid_cron(tmp_path: Path, monkeypatch) -> None:
    manifest = _base_manifest()
    manifest["schedule"] = "this is not cron"
    adapter_dir = tmp_path / "adapter"
    _write_adapter(adapter_dir, manifest)
    vault = tmp_path / "vault"
    vault.mkdir()

    class CronValidatingBackend(FakeBackend):
        def install(self, *, job_id, schedule, cmd, log_path):
            from rufino.runtime.scheduler import validate_cron
            validate_cron(schedule)
            super().install(
                job_id=job_id, schedule=schedule, cmd=cmd, log_path=log_path
            )

    monkeypatch.setattr(
        "rufino.cli._scheduler_backend", lambda: CronValidatingBackend()
    )

    runner = CliRunner()
    result = runner.invoke(cli, [
        "install-ingest", str(adapter_dir),
        "--vault", str(vault),
        "--rufino-home", str(tmp_path / "rh"),
    ])
    assert result.exit_code != 0


def test_uninstall_ingest_invokes_backend(tmp_path: Path, monkeypatch) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    fake = FakeBackend()
    fake.jobs.append("rufino-ingest-someslug-drive-facultad")
    monkeypatch.setattr("rufino.cli._scheduler_backend", lambda: fake)

    runner = CliRunner()
    result = runner.invoke(cli, [
        "uninstall-ingest", "drive-facultad",
        "--vault", str(vault),
    ])
    assert result.exit_code == 0, result.output
    assert len(fake.uninstalls) == 1
    assert fake.uninstalls[0].endswith("-drive-facultad")


def test_list_ingests_outputs_jobs(tmp_path: Path, monkeypatch) -> None:
    fake = FakeBackend()
    fake.jobs = ["rufino-ingest-a-x", "rufino-ingest-b-y"]
    monkeypatch.setattr("rufino.cli._scheduler_backend", lambda: fake)

    runner = CliRunner()
    result = runner.invoke(cli, ["list-ingests"])
    assert result.exit_code == 0, result.output
    assert "rufino-ingest-a-x" in result.output
    assert "rufino-ingest-b-y" in result.output


def test_list_ingests_empty(tmp_path: Path, monkeypatch) -> None:
    fake = FakeBackend()
    monkeypatch.setattr("rufino.cli._scheduler_backend", lambda: fake)

    runner = CliRunner()
    result = runner.invoke(cli, ["list-ingests"])
    assert result.exit_code == 0
