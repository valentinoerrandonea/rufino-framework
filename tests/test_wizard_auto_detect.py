import os
import subprocess
from pathlib import Path


SCRIPT = Path(__file__).resolve().parent.parent / "src" / "rufino" / "wizard" / "auto_detect.sh"


def _run(vault: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["RUFINO_VAULT"] = str(vault)
    return subprocess.run(
        ["bash", str(SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_auto_detect_hints_on_empty_vault(tmp_vault: Path):
    completed = _run(tmp_vault)
    assert completed.returncode == 0
    assert "RUFINO HINT" in completed.stdout


def test_auto_detect_silent_on_populated_vault(tmp_vault: Path):
    (tmp_vault / "real-note.md").write_text("content")
    completed = _run(tmp_vault)
    assert completed.returncode == 0
    assert completed.stdout.strip() == ""


def test_auto_detect_ignores_perfil_md(tmp_vault: Path):
    """perfil.md / preferencias.md don't count as real content."""
    (tmp_vault / "perfil.md").write_text("seed")
    (tmp_vault / "preferencias.md").write_text("seed")
    completed = _run(tmp_vault)
    assert "RUFINO HINT" in completed.stdout


def test_auto_detect_silent_when_vault_env_unset():
    env = {k: v for k, v in os.environ.items() if k != "RUFINO_VAULT"}
    completed = subprocess.run(
        ["bash", str(SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0
    assert completed.stdout.strip() == ""


def test_auto_detect_silent_with_deeply_nested_note(tmp_vault: Path):
    """A note in vault/a/b/c/d/note.md must count — script can't be misled by depth."""
    deep = tmp_vault / "a" / "b" / "c" / "d"
    deep.mkdir(parents=True)
    (deep / "note.md").write_text("content")
    completed = _run(tmp_vault)
    assert completed.returncode == 0
    assert completed.stdout.strip() == ""
