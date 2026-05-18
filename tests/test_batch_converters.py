from pathlib import Path

import pytest

from rufino.engine.process.batch.converters import (
    convert_to_markdown,
    docx_to_md,
    pptx_to_md,
)
from rufino.engine.process.batch.errors import (
    ConversionError,
    UnsupportedFormatError,
)


FIXTURES = Path(__file__).parent / "fixtures" / "batch"


def test_docx_to_md_extracts_text():
    md = docx_to_md(FIXTURES / "hello.docx")
    assert "Hello from docx" in md


def test_pptx_to_md_extracts_per_slide():
    md = pptx_to_md(FIXTURES / "hello.pptx")
    assert "Slide one title" in md
    assert "Slide two title" in md
    assert md.count("## Slide") == 2


def test_convert_md_passthrough(tmp_path):
    src = tmp_path / "note.md"
    src.write_text("# already markdown\n")
    assert convert_to_markdown(src) == "# already markdown\n"


def test_convert_txt_passthrough(tmp_path):
    src = tmp_path / "note.txt"
    src.write_text("plain text\n")
    assert convert_to_markdown(src) == "plain text\n"


def test_convert_docx_dispatches():
    md = convert_to_markdown(FIXTURES / "hello.docx")
    assert "Hello from docx" in md


def test_convert_pptx_dispatches():
    md = convert_to_markdown(FIXTURES / "hello.pptx")
    assert "Slide one title" in md


def test_convert_legacy_doc_raises(tmp_path):
    legacy = tmp_path / "old.doc"
    legacy.write_bytes(b"\xd0\xcf\x11\xe0")
    with pytest.raises(UnsupportedFormatError, match=r"\.doc"):
        convert_to_markdown(legacy)


def test_convert_legacy_ppt_raises(tmp_path):
    legacy = tmp_path / "old.ppt"
    legacy.write_bytes(b"\xd0\xcf\x11\xe0")
    with pytest.raises(UnsupportedFormatError, match=r"\.ppt"):
        convert_to_markdown(legacy)


def test_convert_unknown_raises(tmp_path):
    unknown = tmp_path / "thing.xyz"
    unknown.write_text("?")
    with pytest.raises(UnsupportedFormatError, match=r"\.xyz"):
        convert_to_markdown(unknown)


def test_convert_pdf_does_not_call_converter(tmp_path):
    """PDFs are passthrough — converters should NOT be invoked. The caller
    leaves the PDF in place and lets the worker's Read tool handle it.
    """
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4 ...")
    with pytest.raises(UnsupportedFormatError, match="passthrough"):
        convert_to_markdown(pdf)
