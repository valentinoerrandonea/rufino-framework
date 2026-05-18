import zipfile
from pathlib import Path

import pytest

from rufino.engine.process.batch.stager import (
    StagedCorpus,
    stage_corpus,
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


def test_stage_docx_converted_to_md(tmp_path):
    fixture = Path("tests/fixtures/batch/hello.docx")
    src = tmp_path / "corpus"
    (src / "lit").mkdir(parents=True)
    (src / "lit" / "doc.docx").write_bytes(fixture.read_bytes())

    run_dir = tmp_path / "run"
    stage_corpus(src, run_dir)

    out_md = run_dir / "inbox" / "lit" / "doc.md"
    assert out_md.exists()
    assert "Hello from docx" in out_md.read_text()
    assert not (run_dir / "inbox" / "lit" / "doc.docx").exists()


def test_stage_pptx_converted_to_md(tmp_path):
    fixture = Path("tests/fixtures/batch/hello.pptx")
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
