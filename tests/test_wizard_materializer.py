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
