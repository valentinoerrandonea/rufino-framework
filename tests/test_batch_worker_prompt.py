from pathlib import Path

from rufino.engine.process.batch.planner import WorkerAssignment
from rufino.engine.process.batch.worker_prompt import (
    build_worker_system_prompt,
    build_retry_appendix,
)
from rufino.engine.process.manifest import parse_worker_manifest


_MANIFEST = """
adapter_name: apunte-clase
note_type: apunte_clase
applies_when:
  source_dir: inbox/
  matches_pattern: ["*.md"]
llm: sonnet
mode_default: full
output_schema:
  required:
    title: string
    materia: string
triple_vocabulary:
  - tema-de
  - extiende
tag_axes:
  - axis: materia
    format: "materia/{slug}"
    required: true
destination_path: "apuntes/{materia}/{slug}.md"
qa_triggers:
  - name: materia_ambigua
    condition: "materia not in known_materias"
"""


def test_prompt_contains_all_three_blocks(tmp_path):
    manifest = parse_worker_manifest(_MANIFEST)
    adapter_prompt = "# Adapter instructions\nbe rigorous about triples."
    notes = [tmp_path / "inbox" / "math" / "n01.md"]
    notes[0].parent.mkdir(parents=True)
    notes[0].write_text("# n\n")
    assignment = WorkerAssignment(worker_id="w001", group="math", notes=tuple(notes))
    staging_dir = tmp_path / "staging"
    staging_dir.mkdir()

    prompt = build_worker_system_prompt(
        manifest=manifest,
        adapter_prompt_text=adapter_prompt,
        assignment=assignment,
        vault_slug="my-vault",
        staging_dir=staging_dir,
        vault_concepts_top_n=[],
        run_id="r1",
    )

    assert "worker de Rufino" in prompt
    assert str(notes[0]) in prompt
    assert str(staging_dir) in prompt
    assert "augmented/<slug>.md" in prompt
    assert "deltas/<slug>.json" in prompt
    assert "ASK-USER" in prompt
    assert "be rigorous about triples." in prompt
    assert "ask-rufino-my-vault" in prompt
    assert "tema-de" in prompt
    assert "extiende" in prompt
    assert "title: string" in prompt
    assert "materia: string" in prompt


def test_prompt_includes_top_concepts_when_provided(tmp_path):
    manifest = parse_worker_manifest(_MANIFEST)
    notes = [tmp_path / "n01.md"]
    notes[0].write_text("# n\n")
    assignment = WorkerAssignment(worker_id="w001", group="math", notes=tuple(notes))

    prompt = build_worker_system_prompt(
        manifest=manifest,
        adapter_prompt_text="",
        assignment=assignment,
        vault_slug="v",
        staging_dir=tmp_path / "s",
        vault_concepts_top_n=["dfs", "bfs", "grafos"],
        run_id="r1",
    )
    assert "dfs" in prompt
    assert "bfs" in prompt
    assert "grafos" in prompt


def test_retry_appendix_includes_errors():
    appendix = build_retry_appendix([
        "triple 'expone-a' fuera de vocab",
        "required field 'materia' faltante",
    ])
    assert "RETRY" in appendix
    assert "expone-a" in appendix
    assert "materia" in appendix
