from pathlib import Path

from rufino.wizard.materializer import MaterializationResult, materialize
from rufino.wizard.spec_schema import validate_spec


MINIMAL_SPEC = {
    "vertical_name": "facultad",
    "patterns": ["long_documents_extraction"],
    "entities": ["apunte_clase"],
    "sources": [],
    "processing": [],
    "outputs": [],
    "vocabulary": {"apunte_clase": "apuntes/<slug>.md"},
}


def test_materialize_creates_vault_skeleton(tmp_path: Path):
    vault = tmp_path / "vault"
    claude_home = tmp_path / ".claude"
    state_dir = tmp_path / ".rufino-state"

    spec = validate_spec(MINIMAL_SPEC)
    result = materialize(
        spec=spec,
        vault_root=vault,
        claude_home=claude_home,
        state_dir=state_dir,
    )

    assert isinstance(result, MaterializationResult)
    assert result.success, f"errors: {result.errors}"
    assert vault.exists()
    assert (vault / "perfil.md").exists()
    assert (vault / "questions").exists()


def test_materialize_rejects_entity_without_vocabulary(tmp_path: Path):
    vault = tmp_path / "vault"
    claude_home = tmp_path / ".claude"
    state_dir = tmp_path / ".rufino-state"

    bad_spec = dict(MINIMAL_SPEC)
    bad_spec["vocabulary"] = {}
    spec = validate_spec(bad_spec)

    result = materialize(
        spec=spec,
        vault_root=vault,
        claude_home=claude_home,
        state_dir=state_dir,
    )
    assert result.success is False
    assert any("vocabulary" in e.lower() for e in result.errors)


def test_materialize_rolls_back_adapter_dir_on_install_failure(
    tmp_path: Path, monkeypatch
):
    """If install_memory_loop fails, adapter_dir + manifest.yaml must be cleaned."""
    from rufino.engine.memory_loop.installer import InstallationError
    import rufino.wizard.materializer as mat_mod

    def boom(**kwargs):
        raise InstallationError("simulated failure")
    monkeypatch.setattr(mat_mod, "install_memory_loop", boom)

    spec = validate_spec(MINIMAL_SPEC)
    state_dir = tmp_path / ".rufino-state"
    result = materialize(
        spec=spec,
        vault_root=tmp_path / "vault",
        claude_home=tmp_path / ".claude",
        state_dir=state_dir,
    )
    assert result.success is False
    adapter_dir = state_dir.parent / "adapters" / "memory_loop" / spec.vertical_name
    manifest = adapter_dir / "manifest.yaml"
    assert not manifest.exists(), "manifest.yaml leaked after failed install"
    assert not adapter_dir.exists(), "adapter_dir leaked after failed install"


def test_materialize_returns_result_when_state_dir_unwritable(
    tmp_path: Path, monkeypatch
):
    """Pre-condition failures (e.g. state_dir.mkdir failing) must not raise — surface as MaterializationResult."""
    real_mkdir = Path.mkdir

    def selective_mkdir(self, *args, **kwargs):
        if self.name == ".rufino-state":
            raise PermissionError("simulated")
        return real_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", selective_mkdir)

    spec = validate_spec(MINIMAL_SPEC)
    result = materialize(
        spec=spec,
        vault_root=tmp_path / "vault",
        claude_home=tmp_path / ".claude",
        state_dir=tmp_path / ".rufino-state",
    )
    assert result.success is False
    assert any("simulated" in e.lower() or "permission" in e.lower() for e in result.errors)


def test_materialize_fails_loud_when_adapter_dir_already_exists(tmp_path: Path):
    """Pre-existing adapter_dir (leftover from failed run or concurrent process)
    must cause a clean failure, not silently overwrite manifest.yaml."""
    spec = validate_spec(MINIMAL_SPEC)
    state_dir = tmp_path / ".rufino-state"
    adapter_dir = state_dir.parent / "adapters" / "memory_loop" / spec.vertical_name
    adapter_dir.mkdir(parents=True)

    result = materialize(
        spec=spec,
        vault_root=tmp_path / "vault",
        claude_home=tmp_path / ".claude",
        state_dir=state_dir,
    )
    assert result.success is False
    assert any(
        "exist" in e.lower() or "already" in e.lower()
        for e in result.errors
    ), result.errors


def test_materialize_rolls_back_state_dir_when_we_created_it(tmp_path: Path, monkeypatch):
    """If materialize fails AND it created state_dir, the dir must be removed.
    If state_dir pre-existed, it must be preserved (foreign content)."""
    from rufino.engine.memory_loop.installer import InstallationError
    import rufino.wizard.materializer as mat_mod

    def boom(**kwargs):
        raise InstallationError("simulated failure")
    monkeypatch.setattr(mat_mod, "install_memory_loop", boom)

    spec = validate_spec(MINIMAL_SPEC)
    state_dir = tmp_path / ".fresh_state"
    assert not state_dir.exists()

    result = materialize(
        spec=spec,
        vault_root=tmp_path / "vault",
        claude_home=tmp_path / ".claude",
        state_dir=state_dir,
    )
    assert result.success is False
    # We created state_dir → must be rolled back (rmdir_if_empty leaves only empties).
    assert not state_dir.exists(), "state_dir leaked after rollback"


def test_materialize_preserves_pre_existing_state_dir_on_failure(tmp_path: Path, monkeypatch):
    from rufino.engine.memory_loop.installer import InstallationError
    import rufino.wizard.materializer as mat_mod

    def boom(**kwargs):
        raise InstallationError("simulated failure")
    monkeypatch.setattr(mat_mod, "install_memory_loop", boom)

    spec = validate_spec(MINIMAL_SPEC)
    state_dir = tmp_path / "existing_state"
    state_dir.mkdir()
    (state_dir / "foreign.txt").write_text("user content")

    result = materialize(
        spec=spec,
        vault_root=tmp_path / "vault",
        claude_home=tmp_path / ".claude",
        state_dir=state_dir,
    )
    assert result.success is False
    # We did NOT create state_dir → must NOT be rolled back.
    assert state_dir.exists()
    assert (state_dir / "foreign.txt").read_text() == "user content"
