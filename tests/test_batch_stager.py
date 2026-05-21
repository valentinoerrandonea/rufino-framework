import importlib.util
import shutil
import zipfile
from pathlib import Path

import pytest

from rufino.engine.process.batch.errors import StagingError
from rufino.engine.process.batch.stager import (
    StagedCorpus,
    stage_corpus,
)


_REQUIRES_MAMMOTH = pytest.mark.skipif(
    importlib.util.find_spec("mammoth") is None,
    reason="mammoth not installed",
)
_REQUIRES_PPTX = pytest.mark.skipif(
    importlib.util.find_spec("pptx") is None,
    reason="python-pptx not installed",
)
_REQUIRES_SOFFICE = pytest.mark.skipif(
    shutil.which("soffice") is None,
    reason="soffice not in PATH (LibreOffice not installed)",
)


def _make_zip(path: Path, files: dict[str, bytes], cp437_names: bool = False):
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in files.items():
            if cp437_names:
                info = zipfile.ZipInfo(name.encode("utf-8").decode("cp437"))
                zf.writestr(info, data)
            else:
                zf.writestr(name, data)


def test_stage_directory_with_markdown(tmp_path):
    src = tmp_path / "corpus"
    (src / "math").mkdir(parents=True)
    (src / "math" / "lesson.md").write_text("# math notes\n")

    run_dir = tmp_path / "run"
    staged = stage_corpus(src, run_dir)

    assert isinstance(staged, StagedCorpus)
    assert "math" in staged.groups
    inbox = run_dir / "inbox" / "math"
    assert (inbox / "lesson.md").exists()
    assert "math notes" in (inbox / "lesson.md").read_text()


def test_stage_zip_extracts_and_groups_by_top_folder(tmp_path):
    zip_path = tmp_path / "corpus.zip"
    _make_zip(zip_path, {
        "math/lesson.md": b"# math\n",
        "history/lesson.md": b"# hist\n",
    })

    run_dir = tmp_path / "run"
    staged = stage_corpus(zip_path, run_dir)

    assert set(staged.groups) == {"math", "history"}
    assert (run_dir / "inbox" / "math" / "lesson.md").exists()
    assert (run_dir / "inbox" / "history" / "lesson.md").exists()


def test_stage_files_at_root_go_to_underscore_root(tmp_path):
    src = tmp_path / "corpus"
    src.mkdir()
    (src / "loose.md").write_text("# loose\n")

    run_dir = tmp_path / "run"
    staged = stage_corpus(src, run_dir)
    assert "_root" in staged.groups
    assert (run_dir / "inbox" / "_root" / "loose.md").exists()


def test_stage_pdf_passthrough_unchanged(tmp_path):
    src = tmp_path / "corpus"
    (src / "phys").mkdir(parents=True)
    pdf_bytes = b"%PDF-1.4 fake binary\x00content"
    (src / "phys" / "scan.pdf").write_bytes(pdf_bytes)

    run_dir = tmp_path / "run"
    stage_corpus(src, run_dir)

    out = run_dir / "inbox" / "phys" / "scan.pdf"
    assert out.exists()
    assert out.read_bytes() == pdf_bytes


@_REQUIRES_MAMMOTH
def test_stage_docx_converted_to_md(tmp_path, batch_fixtures_dir):
    fixture = batch_fixtures_dir / "hello.docx"
    src = tmp_path / "corpus"
    (src / "lit").mkdir(parents=True)
    (src / "lit" / "doc.docx").write_bytes(fixture.read_bytes())

    run_dir = tmp_path / "run"
    stage_corpus(src, run_dir)

    out_md = run_dir / "inbox" / "lit" / "doc.md"
    assert out_md.exists()
    assert "Hello from docx" in out_md.read_text()
    assert not (run_dir / "inbox" / "lit" / "doc.docx").exists()


@_REQUIRES_PPTX
def test_stage_pptx_converted_to_md(tmp_path, batch_fixtures_dir):
    fixture = batch_fixtures_dir / "hello.pptx"
    src = tmp_path / "corpus"
    (src / "bio").mkdir(parents=True)
    (src / "bio" / "deck.pptx").write_bytes(fixture.read_bytes())

    run_dir = tmp_path / "run"
    stage_corpus(src, run_dir)

    out_md = run_dir / "inbox" / "bio" / "deck.md"
    assert out_md.exists()
    assert "Slide one title" in out_md.read_text()


def test_stage_skips_unsupported_with_warning(tmp_path, caplog):
    src = tmp_path / "corpus"
    (src / "old").mkdir(parents=True)
    (src / "old" / "legacy.doc").write_bytes(b"\xd0\xcf\x11\xe0")
    (src / "old" / "good.md").write_text("# ok\n")

    run_dir = tmp_path / "run"
    staged = stage_corpus(src, run_dir)

    assert (run_dir / "inbox" / "old" / "good.md").exists()
    assert not (run_dir / "inbox" / "old" / "legacy.md").exists()
    assert not (run_dir / "inbox" / "old" / "legacy.doc").exists()
    assert any("legacy.doc" in r.message for r in caplog.records)
    assert any("legacy.doc" in str(p) for p in staged.skipped)


def test_stage_fixes_cp437_encoded_filenames(tmp_path):
    zip_path = tmp_path / "corpus.zip"
    _make_zip(zip_path, {"matemática/clase-álgebra.md": b"# algebra\n"}, cp437_names=True)

    run_dir = tmp_path / "run"
    staged = stage_corpus(zip_path, run_dir)

    out = run_dir / "inbox" / "matemática" / "clase-álgebra.md"
    assert out.exists(), f"expected {out}; got {list((run_dir / 'inbox').rglob('*'))}"


def test_stage_empty_dir_returns_empty(tmp_path):
    src = tmp_path / "corpus"
    src.mkdir()
    run_dir = tmp_path / "run"
    staged = stage_corpus(src, run_dir)
    assert staged.groups == {}


def test_stage_corrupt_zip_raises(tmp_path):
    from rufino.engine.process.batch.errors import StagingError
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"not a zip")
    run_dir = tmp_path / "run"
    with pytest.raises(StagingError, match="zip"):
        stage_corpus(bad, run_dir)


def test_stage_zip_slip_entries_are_skipped(tmp_path):
    zip_path = tmp_path / "evil.zip"
    _make_zip(zip_path, {
        "../escape.md": b"# escape\n",
        "math/legit.md": b"# legit\n",
    })

    run_dir = tmp_path / "run"
    staged = stage_corpus(zip_path, run_dir)

    assert not (run_dir.parent / "escape.md").exists()
    assert (run_dir / "inbox" / "math" / "legit.md").exists()
    assert any("escape.md" in str(p) for p in staged.skipped)


def test_stage_preserves_nested_subdirs_within_group(tmp_path):
    """Codex H1: math/unit1/lesson.md and math/unit2/lesson.md must not collide."""
    source = tmp_path / "corpus"
    (source / "math" / "unit1").mkdir(parents=True)
    (source / "math" / "unit2").mkdir(parents=True)
    (source / "math" / "unit1" / "lesson.md").write_text("ONE", encoding="utf-8")
    (source / "math" / "unit2" / "lesson.md").write_text("TWO", encoding="utf-8")
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    staged = stage_corpus(source, run_dir)

    math_paths = [p.relative_to(run_dir) for p in staged.groups["math"]]
    assert len(set(math_paths)) == 2, f"paths collided: {math_paths}"
    contents = {p.read_text(encoding="utf-8") for p in staged.groups["math"]}
    assert contents == {"ONE", "TWO"}


@_REQUIRES_MAMMOTH
def test_stage_rejects_collision_after_extension_normalization(
    tmp_path, batch_fixtures_dir
):
    """A .docx that converts to lesson.md and a sibling lesson.md must not silently merge."""
    source = tmp_path / "corpus"
    source.mkdir()
    (source / "lesson.md").write_text("FROM_MD", encoding="utf-8")
    # Use the bundled fixture docx that converts to "lesson.md"
    fixture = batch_fixtures_dir / "hello.docx"
    shutil.copy2(fixture, source / "lesson.docx")
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    with pytest.raises(StagingError, match="collision"):
        stage_corpus(source, run_dir)


@_REQUIRES_SOFFICE
def test_stage_docx_to_pdf_when_multimodal(tmp_path, batch_fixtures_dir):
    """In multimodal mode, a .docx is staged as a .pdf produced by soffice,
    bypassing the mammoth -> markdown path entirely."""
    source = tmp_path / "source"
    (source / "materia1").mkdir(parents=True)
    shutil.copy(batch_fixtures_dir / "hello.docx", source / "materia1" / "apunte.docx")
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    staged = stage_corpus(source, run_dir, multimodal=True)

    assert "materia1" in staged.groups
    files = staged.groups["materia1"]
    assert len(files) == 1
    assert files[0].suffix == ".pdf"
    assert files[0].read_bytes()[:5] == b"%PDF-"


@_REQUIRES_SOFFICE
def test_stage_pptx_to_pdf_when_multimodal(tmp_path, batch_fixtures_dir):
    source = tmp_path / "source"
    (source / "materia1").mkdir(parents=True)
    shutil.copy(batch_fixtures_dir / "hello.pptx", source / "materia1" / "slides.pptx")
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    staged = stage_corpus(source, run_dir, multimodal=True)

    files = staged.groups["materia1"]
    assert files[0].suffix == ".pdf"
    assert files[0].read_bytes()[:5] == b"%PDF-"


@_REQUIRES_MAMMOTH
def test_stage_docx_to_md_when_not_multimodal_default(
    tmp_path, batch_fixtures_dir
):
    """Default behavior (v0.2.x): .docx is flattened to .md via mammoth."""
    source = tmp_path / "source"
    (source / "materia1").mkdir(parents=True)
    shutil.copy(batch_fixtures_dir / "hello.docx", source / "materia1" / "apunte.docx")
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    staged = stage_corpus(source, run_dir)

    files = staged.groups["materia1"]
    assert files[0].suffix == ".md"


def test_stage_multimodal_skips_docx_when_soffice_missing(
    tmp_path, batch_fixtures_dir, monkeypatch, caplog
):
    """If soffice disappears mid-batch, the file is skipped (logged), not
    raised — keeps the rest of the corpus moving."""
    monkeypatch.setattr(
        "rufino.engine.process.batch.converters._which_soffice",
        lambda: None,
    )
    source = tmp_path / "source"
    (source / "materia1").mkdir(parents=True)
    shutil.copy(batch_fixtures_dir / "hello.docx", source / "materia1" / "apunte.docx")
    (source / "materia1" / "other.md").write_text("# survives\n")
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    import logging as _logging
    with caplog.at_level(_logging.WARNING, logger="rufino.engine.process.batch.stager"):
        staged = stage_corpus(source, run_dir, multimodal=True)

    files = staged.groups["materia1"]
    assert [f.name for f in files] == ["other.md"]
    assert any("soffice" in r.getMessage().lower() for r in caplog.records)
