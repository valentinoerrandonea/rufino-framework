import os
from pathlib import Path

import pytest
import yaml


# CWD-independent anchor: tests/conftest.py -> tests/ -> tests/fixtures/...
FAKE_CLAUDE_DIR = (Path(__file__).parent / "fixtures" / "fake_claude").resolve()
BATCH_FIXTURES = (Path(__file__).parent / "fixtures" / "batch").resolve()


@pytest.fixture
def tmp_vault(tmp_path: Path) -> Path:
    """Vault path temporal limpio para cada test."""
    vault = tmp_path / "vault"
    vault.mkdir()
    return vault


@pytest.fixture
def tmp_rufino_home(tmp_path: Path, monkeypatch) -> Path:
    """~/.rufino temporal aislado del filesystem real del user."""
    home = tmp_path / ".rufino"
    home.mkdir()
    monkeypatch.setenv("RUFINO_HOME", str(home))
    return home


@pytest.fixture
def fake_claude_dir() -> Path:
    """Absolute, ``__file__``-anchored path to ``tests/fixtures/fake_claude``."""
    return FAKE_CLAUDE_DIR


@pytest.fixture
def batch_fixtures_dir() -> Path:
    """Absolute, ``__file__``-anchored path to ``tests/fixtures/batch``."""
    return BATCH_FIXTURES


@pytest.fixture
def fake_claude_on_path(monkeypatch):
    """Prepend the fake_claude fixture directory to PATH.

    Tests that need the fake claude binary on $PATH can either:
      * mark a per-file ``autouse`` fixture that delegates to this one, or
      * request ``fake_claude_on_path`` explicitly.

    Anchored to ``__file__`` so it works regardless of pytest's CWD.
    """
    monkeypatch.setenv(
        "PATH", f"{FAKE_CLAUDE_DIR}{os.pathsep}{os.environ['PATH']}"
    )
    yield FAKE_CLAUDE_DIR


# Default manifest body shared across batch tests. Field set matches
# ``parse_worker_manifest``'s required schema; callers may override any
# field via ``manifest_overrides``.
_DEFAULT_MANIFEST: dict = {
    "adapter_name": "x",
    "note_type": "x",
    "applies_when": {"source_dir": "inbox/", "matches_pattern": ["*.md"]},
    "llm": "sonnet",
    "mode_default": "full",
    "output_schema": {"required": {"title": "string", "materia": "string"}},
    "triple_vocabulary": ["tema-de"],
    "tag_axes": [{"axis": "materia", "format": "materia/{slug}"}],
    "destination_path": "apuntes/{slug}.md",
    "batch_size": 10,
}


@pytest.fixture
def batch_adapter(tmp_path):
    """Factory: build a minimal but schema-valid Process worker adapter dir.

    Returns a callable ``make(adapter_dir=None, **manifest_overrides) -> Path``.

    The default manifest passes ``parse_worker_manifest`` and the runner's
    schema checks. ``manifest_overrides`` keys are spread on top of the
    defaults (shallow merge), so callers can swap individual fields without
    duplicating the full manifest body.

    Per-file legacy fixture helpers (``_make_adapter``) consolidated here.
    """

    def _make(adapter_dir: Path | None = None, **manifest_overrides) -> Path:
        adapter_dir = adapter_dir or (tmp_path / "adapter")
        adapter_dir.mkdir(parents=True, exist_ok=True)
        manifest = {**_DEFAULT_MANIFEST, **manifest_overrides}
        (adapter_dir / "manifest.yaml").write_text(
            yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
        )
        (adapter_dir / "prompt.md").write_text(
            "# adapter prompt\n", encoding="utf-8"
        )
        return adapter_dir

    return _make
