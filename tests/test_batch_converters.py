import logging
from pathlib import Path
from types import SimpleNamespace

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


def test_pptx_body_paragraphs_use_hard_break(tmp_path):
    """Body paragraphs in a pptx slide must be separated by a blank line so
    CommonMark renders them as distinct paragraphs (hard break), not a single
    paragraph with a soft line break.
    """
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    blank = prs.slide_layouts[6]  # blank layout — full control over shapes
    slide = prs.slides.add_slide(blank)

    # Title textbox (first shape with text → becomes the slide title).
    title_box = slide.shapes.add_textbox(Inches(1), Inches(0.5), Inches(8), Inches(1))
    title_box.text_frame.text = "The Title"

    # Body textbox with two paragraphs.
    body_box = slide.shapes.add_textbox(Inches(1), Inches(2), Inches(8), Inches(4))
    tf = body_box.text_frame
    tf.text = "First paragraph"
    p2 = tf.add_paragraph()
    p2.text = "Second paragraph"

    out = tmp_path / "two_paragraphs.pptx"
    prs.save(str(out))

    md = pptx_to_md(out)

    assert "First paragraph" in md
    assert "Second paragraph" in md
    # The two body paragraphs must be separated by a blank line.
    assert "First paragraph\n\nSecond paragraph" in md
    # And the single-newline (soft break) form must NOT appear.
    assert "First paragraph\nSecond paragraph" not in md


def test_docx_warnings_are_logged(tmp_path, caplog, monkeypatch):
    """mammoth surfaces unconvertible elements via result.messages — those
    must be emitted as logger warnings, not silently dropped.
    """
    import mammoth

    fake_messages = [
        SimpleNamespace(type="warning", message="image dropped"),
        SimpleNamespace(type="warning", message="unrecognized style 'Foo'"),
    ]
    fake_result = SimpleNamespace(value="# converted body\n", messages=fake_messages)

    def fake_convert_to_markdown(fh):
        return fake_result

    monkeypatch.setattr(mammoth, "convert_to_markdown", fake_convert_to_markdown)

    src = tmp_path / "fake.docx"
    src.write_bytes(b"not a real docx but mammoth is stubbed")

    with caplog.at_level(logging.WARNING, logger="rufino.engine.process.batch.converters"):
        out = docx_to_md(src)

    assert out == "# converted body\n"
    messages = [rec.getMessage() for rec in caplog.records]
    assert any("image dropped" in m for m in messages)
    assert any("unrecognized style 'Foo'" in m for m in messages)
