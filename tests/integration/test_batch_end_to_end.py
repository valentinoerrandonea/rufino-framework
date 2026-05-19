"""End-to-end tests for `rufino process-batch` using the fake claude fixture.

Covers the production paths the inner batch tests bypass:
 * ZIP corpus driven through the CLI entry point (exit-code mapping).
 * Validator-then-retry exhausting into ``failed/<slug>/``.
 * Missing-``claude``-binary exit code 127.
"""
import asyncio
import json
import os
import zipfile
from pathlib import Path

import pytest

pytest.importorskip("mammoth")
pytest.importorskip("pptx")

from rufino.engine.process.batch.runner import run_batch


FAKE_DIR = (Path(__file__).parent.parent / "fixtures" / "fake_claude").resolve()
FIXTURES = (Path(__file__).parent.parent / "fixtures" / "batch").resolve()


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
    assert result.notes_ok == 4, (
        f"all 4 staged notes should land; ok={result.notes_ok} "
        f"failed={result.notes_failed}"
    )
    landed = {p.stem for p in vault.rglob("*.md")
              if ".rufino" not in str(p) and "_meta" not in str(p)}
    assert {"lesson", "scan", "notes", "slides"}.issubset(landed)

    summary = json.loads(
        (vault / ".rufino" / "runs" / result.run_id / "run.json").read_text()
    )
    assert summary["notes_total"] == 4
    assert summary["notes_ok"] == 4


def _make_minimal_setup(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Smallest viable e2e input: vault dir, adapter, and a 1-note corpus.

    Returns ``(vault, adapter, source)``. Matches the helper used by the
    inner ``test_batch_runner`` tests so the two suites stay aligned.
    """
    vault = tmp_path / "vault"
    vault.mkdir()
    adapter = _make_adapter(tmp_path)
    source = tmp_path / "corpus"
    (source / "math").mkdir(parents=True)
    (source / "math" / "n1.md").write_text("# n1\n", encoding="utf-8")
    return vault, adapter, source


def _build_test_zip(tmp_path: Path) -> Path:
    """Build a corpus ZIP with one ``.md``, one ``.docx``, one ``.txt``.

    The docx body reuses the bundled fixture so converters.convert_to_markdown
    exercises the real mammoth pipeline. Files are placed under a top-level
    ``notes/`` directory so the stager groups them coherently (anything at
    the zip root lands in the synthetic ``_root`` group, which is still
    valid but less representative of a real corpus).
    """
    zip_path = tmp_path / "corpus.zip"
    docx_bytes = (FIXTURES / "hello.docx").read_bytes()
    with zipfile.ZipFile(zip_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("notes/md_note.md", "# md_note\nhello from md\n")
        zf.writestr("notes/docx_note.docx", docx_bytes)
        zf.writestr("notes/txt_note.txt", "hello from txt\n")
    return zip_path


def test_e2e_zip_input_through_cli(tmp_path, monkeypatch):
    """E2E with a ZIP corpus driven through the CLI: exit 0 + vault state."""
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "augment")
    vault = tmp_path / "vault"
    vault.mkdir()
    adapter = _make_adapter(tmp_path)
    zip_path = _build_test_zip(tmp_path)

    from click.testing import CliRunner
    from rufino.cli import cli

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "process-batch", str(zip_path),
            "--adapter", str(adapter),
            "--vault", str(vault),
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    landed = list((vault / "apuntes").glob("*.md"))
    slugs = {p.stem for p in landed}
    assert slugs == {"md_note", "docx_note", "txt_note"}, (
        f"unexpected slugs landed: {slugs}"
    )


def test_e2e_retry_exhausts_files_go_to_failed(tmp_path, monkeypatch):
    """Worker always emits invalid output → retry exhausts → slug in failed/.

    Exercises the validator + retry interaction end-to-end: the worker
    produces output that fails frontmatter validation, retry fires (and
    also fails because the mode is sticky), and the bouncer writes the
    ``failed/<slug>/error.json`` marker.
    """
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "augment_bad")
    vault, adapter, source = _make_minimal_setup(tmp_path)

    result = asyncio.run(run_batch(
        source=source, adapter_dir=adapter, vault_root=vault,
        workers=1, batch_size=1, dry_run=False,
        skip_consolidator=True, timeout_seconds=30.0,
    ))

    assert result.notes_failed >= 1, (
        f"augment_bad should bounce ≥1 note to failed; "
        f"ok={result.notes_ok} failed={result.notes_failed}"
    )
    assert result.notes_ok == 0
    run_dir = vault / ".rufino" / "runs" / result.run_id
    # _bounce_to_failed writes under <staging_dir>/failed/<slug>/, where
    # staging_dir is run_dir/workers/<worker_id>. Globbing across worker
    # dirs avoids hard-coding the worker_id naming scheme.
    failed_markers = list(run_dir.glob("workers/*/failed/*/error.json"))
    assert failed_markers, (
        "expected at least one failed/<slug>/error.json marker on disk; "
        f"run_dir contents: {sorted(p.relative_to(run_dir) for p in run_dir.rglob('*'))}"
    )


def test_e2e_cli_returns_127_when_claude_missing(tmp_path, monkeypatch):
    """CLI exit-code mapping when ``claude`` is not in PATH."""
    # Override the autouse fixture's PATH: strip the fake_claude shim AND any
    # real `claude` on the machine so subprocess.run raises
    # FileNotFoundError(filename="claude"). Empty PATH is the only way to
    # guarantee no stray installation (homebrew, ~/.local/bin, /usr/local/bin)
    # interferes on dev or CI machines.
    monkeypatch.setenv("PATH", "")
    vault, adapter, source = _make_minimal_setup(tmp_path)

    from click.testing import CliRunner
    from rufino.cli import cli

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "process-batch", str(source),
            "--adapter", str(adapter),
            "--vault", str(vault),
        ],
    )

    assert result.exit_code == 127, (
        f"expected exit 127 when claude missing; got {result.exit_code}\n"
        f"output: {result.output}"
    )
