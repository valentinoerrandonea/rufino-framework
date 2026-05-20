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


def test_install_ingest_resolves_paths_to_absolute(tmp_path: Path, monkeypatch) -> None:
    """F9 — install-ingest debe resolver paths a absolutos antes de pasarlos al cron.

    Si el cron corre con un cwd distinto al del install (siempre), rutas
    relativas en el cmd hacen fallar el `rufino ingest <rel-path>`.
    """
    vault = tmp_path / "vault"
    vault.mkdir()
    adapter_dir = tmp_path / "adapter"
    _write_adapter(adapter_dir, _base_manifest())

    fake = FakeBackend()
    monkeypatch.setattr("rufino.cli._scheduler_backend", lambda: fake)

    import os
    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        runner = CliRunner()
        result = runner.invoke(cli, [
            "install-ingest", "adapter",
            "--vault", "vault",
            "--rufino-home", str(tmp_path / "rh"),
        ])
    finally:
        os.chdir(cwd)
    assert result.exit_code == 0, result.output
    cmd = fake.installs[0]["cmd"]
    # Ambos paths deben aparecer absolutos en el cmd registrado al cron.
    assert str(adapter_dir.resolve()) in cmd
    assert str(vault.resolve()) in cmd


def test_install_ingest_scheduler_uninstall_rollback_uses_backend(
    tmp_path: Path, monkeypatch
) -> None:
    """CR-1 — La rollback del install registrado debe ir por backend.uninstall,
    NO por el handler _plist_uninstall (que espera path absoluto y haría no-op
    cuando target=job_id).
    """
    vault = tmp_path / "vault"
    vault.mkdir()
    adapter_dir = tmp_path / "adapter"
    _write_adapter(adapter_dir, _base_manifest())

    fake = FakeBackend()
    monkeypatch.setattr("rufino.cli._scheduler_backend", lambda: fake)
    # El scheduler_uninstall handler resuelve el backend via get_backend(),
    # así que tenemos que patchearlo también ahí.
    monkeypatch.setattr("rufino.runtime.scheduler.get_backend", lambda: fake)

    rh = tmp_path / "rh"
    runner = CliRunner()
    result = runner.invoke(cli, [
        "install-ingest", str(adapter_dir),
        "--vault", str(vault),
        "--rufino-home", str(rh),
    ])
    assert result.exit_code == 0, result.output

    # Ahora simulamos rollback manual cargando el tx log y disparándolo.
    from rufino.runtime.transaction_log import TransactionLog
    job_id = fake.installs[0]["job_id"]
    tx_log = TransactionLog.load(rh / "tx" / f"install-ingest-{job_id}.json")
    tx_log.rollback()

    assert fake.uninstalls == [job_id], (
        "scheduler_uninstall rollback debe ir por backend.uninstall(job_id=...)"
    )


def test_install_ingest_rolls_back_log_dir_on_backend_failure(tmp_path: Path, monkeypatch) -> None:
    """F9 — si backend.install lanza, el log_dir creado debe limpiarse."""
    vault = tmp_path / "vault"
    vault.mkdir()
    adapter_dir = tmp_path / "adapter"
    _write_adapter(adapter_dir, _base_manifest())

    class BoomBackend:
        def install(self, *, job_id, schedule, cmd, log_path):
            raise RuntimeError("scheduler unreachable")

    monkeypatch.setattr("rufino.cli._scheduler_backend", lambda: BoomBackend())
    rh = tmp_path / "rh-failed"

    runner = CliRunner()
    result = runner.invoke(cli, [
        "install-ingest", str(adapter_dir),
        "--vault", str(vault),
        "--rufino-home", str(rh),
    ])
    assert result.exit_code != 0
    # logs/ dir creado pero después rollback debe haberlo eliminado si estaba vacío.
    # Se acepta que logs/ exista si tenía contenido previo, pero acá no había.
    if (rh / "logs").exists():
        assert list((rh / "logs").iterdir()) == []


def test_install_ingest_rejects_invalid_adapter_name(tmp_path: Path) -> None:
    """F9 — adapter_name con chars peligrosos (spaces, slashes) debe fail-fast."""
    vault = tmp_path / "vault"
    vault.mkdir()
    adapter_dir = tmp_path / "adapter"
    bad_manifest = _base_manifest()
    bad_manifest["adapter_name"] = "foo/bar"
    _write_adapter(adapter_dir, bad_manifest)

    runner = CliRunner()
    result = runner.invoke(cli, [
        "install-ingest", str(adapter_dir),
        "--vault", str(vault),
        "--rufino-home", str(tmp_path / "rh"),
    ])
    assert result.exit_code != 0
    assert "adapter_name" in result.output.lower() or "invalid" in result.output.lower()


def test_install_ingest_rejects_adapter_name_with_spaces(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    adapter_dir = tmp_path / "adapter"
    bad_manifest = _base_manifest()
    bad_manifest["adapter_name"] = "foo bar"
    _write_adapter(adapter_dir, bad_manifest)

    runner = CliRunner()
    result = runner.invoke(cli, [
        "install-ingest", str(adapter_dir),
        "--vault", str(vault),
        "--rufino-home", str(tmp_path / "rh"),
    ])
    assert result.exit_code != 0
