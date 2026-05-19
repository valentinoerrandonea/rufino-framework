from pathlib import Path

from rufino.wizard.post_bootstrap_docs import render_user_readme
from rufino.wizard.spec_schema import validate_spec


SPEC = {
    "vertical_name": "facultad",
    "patterns": ["long_documents_extraction"],
    "entities": ["apunte_clase", "materia"],
    "sources": [{
        "adapter_name": "drive-pdfs",
        "source_name": "gdrive",
        "output_mode": "import_raw",
        "schedule": None,
        "auth": {"type": "none"},
        "target_inbox": "inbox/cufona/",
        "process_with": "apunte-clase",
        "trigger": "immediate",
    }],
    "processing": [{
        "adapter_name": "apunte-clase",
        "note_type": "apunte_clase",
        "applies_when": {"source_dir": "inbox/"},
        "llm": "sonnet",
        "output_schema": {"required": {"title": "string"}, "optional": {}},
        "triple_vocabulary": ["tema-de"],
        "tag_axes": [{"axis": "materia", "format": "materia/<slug>"}],
        "destination_path": "apuntes/{slug}.md",
        "qa_triggers": [],
        "context_injectors": [],
        "batch_size": 10,
        "prompt_instructions": "# Procesá apuntes\n",
    }],
    "outputs": [{
        "adapter_name": "digest-semanal",
        "trigger": {"type": "cron", "expression": "0 18 * * 5"},
        "query": [{"name": "all", "expression": "tag:apunte"}],
        "delivery": [{"channel": "file", "path": "digests/{date}.md"}],
        "template_body": "# Digest semanal\n",
    }],
    "vocabulary": {
        "apunte_clase": "apuntes/<materia>/<YYYY-MM-DD>-<slug>.md",
        "materia": "materias/<slug>.md",
    },
}


def test_readme_in_user_language():
    spec = validate_spec(SPEC)
    readme = render_user_readme(spec)
    lowered = readme.lower()
    # User-facing language — no technical jargon
    for jargon in ("manifest", "adapter", "primitive", "frontmatter"):
        assert jargon not in lowered, f"jargon leaked: {jargon!r}"
    # Has expected sections
    assert "Qué tenés acá" in readme
    assert "Cómo agregar cosas" in readme
    assert "Cómo encontrar cosas" in readme
    # Lists the user's entities
    assert "apunte" in lowered


def test_readme_mentions_vertical_name():
    spec = validate_spec(SPEC)
    readme = render_user_readme(spec)
    assert "facultad" in readme


def test_readme_renders_cron_suffix_for_outputs():
    """The cron expression must surface in the user-facing README so the
    reader knows when each digest fires. MappingProxy guard regression."""
    spec = validate_spec(SPEC)
    readme = render_user_readme(spec)
    assert "0 18 * * 5" in readme


def test_readme_handles_no_outputs():
    spec_no_out = dict(SPEC)
    spec_no_out["outputs"] = []
    spec = validate_spec(spec_no_out)
    readme = render_user_readme(spec)
    # No outputs -> no "Vas a recibir" section
    assert "Vas a recibir" not in readme


def test_materializer_writes_user_readme(tmp_path: Path):
    from rufino.wizard.materializer import materialize

    spec = validate_spec(SPEC)
    result = materialize(
        spec=spec,
        vault_root=tmp_path / "vault",
        claude_home=tmp_path / ".claude",
        state_dir=tmp_path / ".rufino-state",
    )
    assert result.success, f"errors: {result.errors}"
    readme = tmp_path / "vault" / "README.md"
    assert readme.exists()
    content = readme.read_text(encoding="utf-8")
    assert "facultad" in content
