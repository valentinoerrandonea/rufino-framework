"""End-to-end tests for the process-batch top-level runner.

Two cases:
  - dry_run stops after PLAN (no worker dirs, plan.json written).
  - full run with skip_consolidator commits an augmented note into the
    vault canon via the naive-commit fallback path.
"""
import asyncio
import os
from pathlib import Path

import pytest

from rufino.engine.process.batch.runner import (
    BatchRunResult,
    run_batch,
)


FAKE_DIR = Path(__file__).parent / "fixtures" / "fake_claude"


@pytest.fixture(autouse=True)
def _fake_claude(monkeypatch):
    monkeypatch.setenv("PATH", str(FAKE_DIR.resolve()) + os.pathsep + os.environ["PATH"])


def _make_adapter(tmp_path: Path) -> Path:
    adapter = tmp_path / "adapter"
    adapter.mkdir()
    (adapter / "manifest.yaml").write_text("""
adapter_name: x
note_type: x
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
batch_size: 5
""")
    (adapter / "prompt.md").write_text("# instructions\n")
    return adapter


def test_dry_run_stops_after_plan(tmp_path, monkeypatch):
    adapter = _make_adapter(tmp_path)
    source = tmp_path / "corpus"
    (source / "math").mkdir(parents=True)
    (source / "math" / "n1.md").write_text("# n1\n")
    vault = tmp_path / "vault"

    monkeypatch.setenv("FAKE_CLAUDE_MODE", "augment")
    result = asyncio.run(run_batch(
        source=source, adapter_dir=adapter, vault_root=vault,
        workers=None, batch_size=None, dry_run=True,
    ))
    assert result.dry_run is True
    run_dir = vault / ".rufino" / "runs" / result.run_id
    assert (run_dir / "plan.json").exists()
    assert not (run_dir / "workers").exists()


def test_full_run_commits(tmp_path, monkeypatch):
    adapter = _make_adapter(tmp_path)
    source = tmp_path / "corpus"
    (source / "math").mkdir(parents=True)
    (source / "math" / "n1.md").write_text("# n1\n")
    vault = tmp_path / "vault"
    (vault / "_meta").mkdir(parents=True)
    (vault / "_meta" / "_tags.md").write_text("")

    monkeypatch.setenv("FAKE_CLAUDE_MODE", "augment")
    result = asyncio.run(run_batch(
        source=source, adapter_dir=adapter, vault_root=vault,
        workers=2, batch_size=None, dry_run=False,
        skip_consolidator=True,
    ))
    assert isinstance(result, BatchRunResult)
    assert result.notes_ok >= 1
    landed = [p for p in vault.rglob("n1.md") if ".rufino" not in str(p)]
    assert landed, "no committed note in vault canon"
