"""End-to-end test for `rufino process-batch` using the fake claude fixture."""
import asyncio
import json
import os
from pathlib import Path

import pytest

pytest.importorskip("mammoth")
pytest.importorskip("pptx")

from rufino.engine.process.batch.runner import run_batch


FAKE_DIR = Path("tests/fixtures/fake_claude").resolve()
FIXTURES = Path("tests/fixtures/batch")


@pytest.fixture(autouse=True)
def _fake_claude_on_path(monkeypatch):
    monkeypatch.setenv("PATH", str(FAKE_DIR) + os.pathsep + os.environ["PATH"])


def _make_adapter(tmp: Path) -> Path:
    adapter = tmp / "adapter"
    adapter.mkdir()
    (adapter / "manifest.yaml").write_text("""
adapter_name: apunte-clase
note_type: apunte_clase
applies_when: {source_dir: inbox/, matches_pattern: ["*.md"]}
llm: sonnet
mode_default: full
output_schema:
  required:
    title: string
    materia: string
triple_vocabulary: [tema-de]
tag_axes: [{axis: materia, format: "materia/{slug}"}]
destination_path: "apuntes/{slug}.md"
batch_size: 10
""")
    (adapter / "prompt.md").write_text("# Instrucciones para el adapter\n")
    return adapter


def test_full_pipeline_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "augment")

    adapter = _make_adapter(tmp_path)
    source = tmp_path / "corpus"
    (source / "math").mkdir(parents=True)
    (source / "history").mkdir(parents=True)
    (source / "math" / "lesson.md").write_text("# math 1\n")
    (source / "math" / "scan.pdf").write_bytes(b"%PDF-1.4 fake")
    (source / "history" / "notes.docx").write_bytes(
        (FIXTURES / "hello.docx").read_bytes()
    )
    (source / "history" / "slides.pptx").write_bytes(
        (FIXTURES / "hello.pptx").read_bytes()
    )

    vault = tmp_path / "vault"
    (vault / "_meta").mkdir(parents=True)
    (vault / "_meta" / "_tags.md").write_text("")

    result = asyncio.run(run_batch(
        source=source, adapter_dir=adapter, vault_root=vault,
        workers=2, batch_size=None, dry_run=False,
        skip_consolidator=True,
    ))
    assert result.notes_total == 4
    assert result.notes_ok >= 3
    landed = {p.name for p in vault.rglob("*.md")
              if ".rufino" not in str(p) and "_meta" not in str(p)}
    assert "lesson.md" in landed

    summary = json.loads(
        (vault / ".rufino" / "runs" / result.run_id / "run.json").read_text()
    )
    assert summary["notes_total"] == 4
