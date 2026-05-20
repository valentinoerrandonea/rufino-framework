"""Verifica que materialize() materializa adapters Ingest/Process/Output
de un spec completo (no solo el skeleton + memory loop)."""
from pathlib import Path

import yaml

from rufino.runtime.vault_slug import compute_vault_slug
from rufino.wizard.materializer import materialize
from rufino.wizard.spec_schema import validate_spec


_RAW_SPEC = {
    "vertical_name": "facultad",
    "patterns": ["long_documents_extraction"],
    "entities": ["apunte_clase"],
    "vocabulary": {"apunte_clase": "apuntes/<slug>.md"},
    "sources": [
        {
            "adapter_name": "drive-cufona",
            "source_name": "gdrive",
            "output_mode": "import_raw",
            "schedule": "*/30 * * * *",
            "auth": {"type": "oauth2", "keychain_service": "rufino-gdrive"},
            "target_inbox": "inbox/cufona/",
            "process_with": "apunte-clase",
            "trigger": "immediate",
        }
    ],
    "processing": [
        {
            "adapter_name": "apunte-clase",
            "note_type": "apunte_clase",
            "applies_when": {"source_dir": "inbox/cufona/"},
            "llm": "sonnet",
            "output_schema": {"required": {"title": "string"}, "optional": {}},
            "triple_vocabulary": ["tema-de"],
            "tag_axes": [
                {"axis": "materia", "format": "materia/<slug>", "required": True, "min": 1}
            ],
            "destination_path": "apuntes/{slug}.md",
            "qa_triggers": [],
            "context_injectors": [],
            "batch_size": 10,
            "prompt_instructions": "# Procesá apuntes\n",
        }
    ],
    "outputs": [
        {
            "adapter_name": "digest-semanal",
            "trigger": {"type": "cron", "expression": "0 9 * * 1"},
            "query": [{"name": "items", "expression": "tag:tipo/apunte_clase"}],
            "delivery": [{"channel": "file", "path": "reports/digest.md"}],
            "template_body": "# Digest\n{% for i in items %}- {{ i.title }}\n{% endfor %}\n",
        }
    ],
}


def test_materialize_creates_all_adapter_dirs(tmp_path: Path) -> None:
    spec = validate_spec(_RAW_SPEC)
    vault = tmp_path / "vault"
    state_dir = tmp_path / ".rufino-state"
    result = materialize(
        spec=spec,
        vault_root=vault,
        claude_home=tmp_path / ".claude",
        state_dir=state_dir,
    )
    assert result.success, result.errors
    slug = compute_vault_slug(vault)

    base = state_dir.parent
    ingest_dir = base / "adapters" / "ingest" / slug / "drive-cufona"
    process_dir = base / "adapters" / "process" / slug / "apunte-clase"
    output_dir = base / "adapters" / "output" / slug / "digest-semanal"

    assert (ingest_dir / "manifest.yaml").exists()
    assert (process_dir / "manifest.yaml").exists()
    assert (process_dir / "prompt.md").exists()
    assert (output_dir / "manifest.yaml").exists()
    assert (output_dir / "template.md").exists()


def test_materialize_process_adapter_yaml_round_trip(tmp_path: Path) -> None:
    spec = validate_spec(_RAW_SPEC)
    state_dir = tmp_path / ".rufino-state"
    vault = tmp_path / "vault"
    result = materialize(
        spec=spec,
        vault_root=vault,
        claude_home=tmp_path / ".claude",
        state_dir=state_dir,
    )
    assert result.success, result.errors
    slug = compute_vault_slug(vault)
    process_yaml = (
        state_dir.parent / "adapters" / "process" / slug / "apunte-clase" / "manifest.yaml"
    ).read_text(encoding="utf-8")
    parsed = yaml.safe_load(process_yaml)
    assert parsed["note_type"] == "apunte_clase"
    assert parsed["llm"] == "sonnet"


def test_materialize_rolls_back_adapter_dirs_on_failure(
    tmp_path: Path, monkeypatch
) -> None:
    from rufino.engine.memory_loop.installer import InstallationError
    import rufino.wizard.materializer as mat_mod

    def boom(**kwargs):
        raise InstallationError("simulated failure")

    monkeypatch.setattr(mat_mod, "install_memory_loop", boom)
    spec = validate_spec(_RAW_SPEC)
    vault = tmp_path / "vault"
    state_dir = tmp_path / ".rufino-state"
    result = materialize(
        spec=spec,
        vault_root=vault,
        claude_home=tmp_path / ".claude",
        state_dir=state_dir,
        install_hooks=True,
    )
    assert result.success is False
    slug = compute_vault_slug(vault)
    base = state_dir.parent
    expected_leaves = [
        ("ingest", "drive-cufona"),
        ("process", "apunte-clase"),
        ("output", "digest-semanal"),
    ]
    for prim, adapter_name in expected_leaves:
        leaf = base / "adapters" / prim / slug / adapter_name
        assert not leaf.exists(), f"{prim}/{adapter_name} adapter dir leaked after rollback"
