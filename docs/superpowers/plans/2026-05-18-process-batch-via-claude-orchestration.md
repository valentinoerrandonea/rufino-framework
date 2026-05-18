# process-batch via Claude orchestration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `rufino process-batch <zip-or-dir>` — a CLI command that converts a raw corpus into augmented vault notes by orchestrating Claude Code workers under a six-stage flow (STAGE → PLAN → DISPATCH → VALIDATE+RETRY → CONSOLIDATE → COMMIT).

**Architecture:** Rufino spawns `claude` headless subprocesses as workers (no embedded LLM client). Workers run via the standard library subprocess module with argv passed as a list (never via a shell), wrapped in `asyncio.to_thread` for bounded parallelism. Workers write to per-worker staging dirs under `<vault>/.rufino/runs/<run-id>/`. The vault canon is read-only until the final COMMIT, which applies a consolidation plan through the existing `TransactionLog` so any failure rolls back cleanly.

**Tech Stack:** Python 3.11+, click (CLI), asyncio + subprocess.run (parallelism), mammoth (docx→md), python-pptx (pptx→md), PyYAML (manifests + frontmatter), pytest (testing).

**Spec reference:** `docs/superpowers/specs/2026-05-18-process-batch-via-claude-orchestration-design.md` — sections referenced as §N below.

---

## Task 1: Add `batch_size` field to adapter manifest

**Files:**
- Modify: `src/rufino/engine/process/manifest.py`
- Test: `tests/test_process_manifest_batch_size.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_process_manifest_batch_size.py`:

```python
import pytest

from rufino.engine.process.manifest import (
    ManifestParseError,
    parse_worker_manifest,
)


_MIN_MANIFEST = """
adapter_name: x
note_type: x
applies_when:
  source_dir: inbox/
  matches_pattern: ["*.md"]
llm: sonnet
mode_default: full
output_schema:
  required:
    title: string
triple_vocabulary:
  - tema-de
tag_axes:
  - axis: materia
    format: "materia/{slug}"
destination_path: "apuntes/{slug}.md"
"""


def test_batch_size_defaults_to_10_when_absent():
    m = parse_worker_manifest(_MIN_MANIFEST)
    assert m.batch_size == 10


def test_batch_size_respects_manifest_value():
    m = parse_worker_manifest(_MIN_MANIFEST + "\nbatch_size: 25\n")
    assert m.batch_size == 25


def test_batch_size_zero_rejected():
    with pytest.raises(ManifestParseError, match="batch_size"):
        parse_worker_manifest(_MIN_MANIFEST + "\nbatch_size: 0\n")


def test_batch_size_negative_rejected():
    with pytest.raises(ManifestParseError, match="batch_size"):
        parse_worker_manifest(_MIN_MANIFEST + "\nbatch_size: -1\n")


def test_batch_size_non_int_rejected():
    with pytest.raises(ManifestParseError, match="batch_size"):
        parse_worker_manifest(_MIN_MANIFEST + "\nbatch_size: foo\n")
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/test_process_manifest_batch_size.py -v`
Expected: FAIL — `WorkerAdapterManifest` has no `batch_size` attribute.

- [ ] **Step 3: Add the field to the dataclass and parser**

Edit `src/rufino/engine/process/manifest.py`. Append `batch_size` to the dataclass:

```python
@dataclass(frozen=True)
class WorkerAdapterManifest:
    adapter_name: str
    note_type: str
    applies_when: Mapping[str, Any]
    llm: str
    mode_default: str
    output_schema: Mapping[str, Any]
    triple_vocabulary: tuple[str, ...]
    tag_axes: tuple[Mapping[str, Any], ...]
    destination_path: str
    qa_triggers: tuple[Mapping[str, Any], ...]
    context_injectors: tuple[Mapping[str, Any], ...]
    transform_hook: str | None = None
    batch_size: int = 10
```

In `parse_worker_manifest`, before the final return, add:

```python
    batch_size_raw = raw.get("batch_size", 10)
    if not isinstance(batch_size_raw, int) or isinstance(batch_size_raw, bool):
        raise ManifestParseError(
            f"batch_size must be a positive integer, got {batch_size_raw!r}"
        )
    if batch_size_raw < 1:
        raise ManifestParseError(
            f"batch_size must be >= 1, got {batch_size_raw}"
        )
```

Add `batch_size=batch_size_raw,` to the return.

- [ ] **Step 4: Run to confirm pass**

Run: `pytest tests/test_process_manifest_batch_size.py -v`
Expected: PASS for all 5 tests.

- [ ] **Step 5: Run the manifest suite to confirm no regressions**

Run: `pytest tests/ -k "manifest" -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add tests/test_process_manifest_batch_size.py src/rufino/engine/process/manifest.py
git commit -m "feat(process): add batch_size field to worker manifest"
```

---

## Task 2: Scaffold `batch/` package with error hierarchy

**Files:**
- Create: `src/rufino/engine/process/batch/__init__.py`
- Create: `src/rufino/engine/process/batch/errors.py`
- Test: `tests/test_batch_errors.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_batch_errors.py`:

```python
from rufino.engine.process.batch.errors import (
    BatchError,
    UnsupportedFormatError,
    ConversionError,
    StagingError,
    DispatchError,
    WorkerSessionExpiredError,
    ConsolidationError,
)


def test_all_errors_inherit_from_base():
    for cls in (
        UnsupportedFormatError,
        ConversionError,
        StagingError,
        DispatchError,
        WorkerSessionExpiredError,
        ConsolidationError,
    ):
        assert issubclass(cls, BatchError)
        assert issubclass(cls, Exception)


def test_errors_carry_message():
    err = UnsupportedFormatError("file.doc")
    assert "file.doc" in str(err)
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/test_batch_errors.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement**

Create `src/rufino/engine/process/batch/__init__.py`:

```python
"""rufino process-batch — orchestrate Claude Code workers over a raw corpus."""
```

Create `src/rufino/engine/process/batch/errors.py`:

```python
class BatchError(Exception):
    """Base error for the process-batch pipeline."""


class UnsupportedFormatError(BatchError):
    """Raised when an input file's extension is not supported in v0.1.0."""


class ConversionError(BatchError):
    """Raised when docx/pptx → markdown conversion fails."""


class StagingError(BatchError):
    """Raised when staging a corpus fails irrecoverably (bad ZIP, etc.)."""


class DispatchError(BatchError):
    """Raised when worker dispatch hits an unrecoverable condition."""


class WorkerSessionExpiredError(DispatchError):
    """Raised when `claude` reports an expired session — aborts the run."""


class ConsolidationError(BatchError):
    """Raised when the consolidator output is unusable (bad schema, etc.)."""
```

- [ ] **Step 4: Run to confirm pass**

Run: `pytest tests/test_batch_errors.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/rufino/engine/process/batch/__init__.py src/rufino/engine/process/batch/errors.py tests/test_batch_errors.py
git commit -m "feat(batch): scaffold batch package with error hierarchy"
```

---

## Task 3: Implement format converters (docx, pptx)

**Files:**
- Create: `src/rufino/engine/process/batch/converters.py`
- Test: `tests/test_batch_converters.py` (new)
- Test fixtures: `tests/fixtures/batch/hello.docx`, `tests/fixtures/batch/hello.pptx` (new — see step 3)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_batch_converters.py`:

```python
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
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/test_batch_converters.py -v`
Expected: FAIL — module + fixtures missing.

- [ ] **Step 3: Create fixture files**

Save the following helper script as `/tmp/make_batch_fixtures.py` and run it:

```python
from pathlib import Path
from docx import Document
from pptx import Presentation
from pptx.util import Inches

out = Path("tests/fixtures/batch")
out.mkdir(parents=True, exist_ok=True)

doc = Document()
doc.add_paragraph("Hello from docx")
doc.add_paragraph("Second paragraph with áccénts")
doc.save(out / "hello.docx")

prs = Presentation()
for title in ("Slide one title", "Slide two title"):
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    tx = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(6), Inches(1)).text_frame
    tx.text = title
prs.save(out / "hello.pptx")
print("fixtures written")
```

Run: `pip install python-docx python-pptx && python /tmp/make_batch_fixtures.py`

- [ ] **Step 4: Implement converters.py**

Create `src/rufino/engine/process/batch/converters.py`:

```python
"""Format converters for process-batch input files.

Markdown and plain text pass through unchanged. .docx → markdown via mammoth.
.pptx → markdown via python-pptx (one section per slide). Legacy formats
(.doc, .ppt) and unknown extensions raise UnsupportedFormatError. PDFs also
raise — they are passthrough at the stager level (the worker reads them via
the Read tool directly).
"""
from pathlib import Path

from rufino.engine.process.batch.errors import (
    ConversionError,
    UnsupportedFormatError,
)


def docx_to_md(path: Path) -> str:
    """Convert a .docx file to markdown using mammoth."""
    import mammoth
    try:
        with open(path, "rb") as fh:
            result = mammoth.convert_to_markdown(fh)
        return result.value
    except Exception as e:
        raise ConversionError(f"docx conversion failed for {path}: {e}") from e


def pptx_to_md(path: Path) -> str:
    """Convert a .pptx file to markdown, one '## Slide N: title' section per slide."""
    from pptx import Presentation
    try:
        prs = Presentation(str(path))
    except Exception as e:
        raise ConversionError(f"pptx open failed for {path}: {e}") from e

    sections: list[str] = []
    for idx, slide in enumerate(prs.slides, start=1):
        texts: list[str] = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    line = "".join(run.text for run in para.runs).strip()
                    if line:
                        texts.append(line)
        title = texts[0] if texts else f"(empty slide {idx})"
        body = "\n".join(texts[1:]) if len(texts) > 1 else ""
        section = f"## Slide {idx}: {title}\n"
        if body:
            section += f"\n{body}\n"
        sections.append(section)
    return "\n".join(sections)


def convert_to_markdown(path: Path) -> str:
    """Dispatch to the right converter (or passthrough) based on extension.

    Raises UnsupportedFormatError for unsupported extensions, legacy formats,
    and PDFs (which are passthrough at the stager level — callers should not
    invoke this for PDFs).
    """
    suffix = path.suffix.lower()
    if suffix in (".md", ".txt"):
        return path.read_text(encoding="utf-8", errors="replace")
    if suffix == ".docx":
        return docx_to_md(path)
    if suffix == ".pptx":
        return pptx_to_md(path)
    if suffix == ".pdf":
        raise UnsupportedFormatError(
            f"{suffix} is passthrough — copy the file verbatim; "
            f"do not call convert_to_markdown"
        )
    if suffix in (".doc", ".ppt"):
        raise UnsupportedFormatError(
            f"legacy {suffix} requires pandoc/LibreOffice — convert to "
            f"{suffix}x first (out of scope for v0.1.0)"
        )
    raise UnsupportedFormatError(f"{suffix} not supported")
```

- [ ] **Step 5: Add deps to pyproject.toml**

Edit `pyproject.toml`. In `[project] dependencies`, add:

```
"mammoth>=1.6",
"python-pptx>=0.6",
```

Run: `pipx reinstall -e .` (or `pip install -e .` if dev env).

- [ ] **Step 6: Run to confirm pass**

Run: `pytest tests/test_batch_converters.py -v`
Expected: PASS for all 10 tests.

- [ ] **Step 7: Commit**

```bash
git add src/rufino/engine/process/batch/converters.py tests/test_batch_converters.py tests/fixtures/batch/hello.docx tests/fixtures/batch/hello.pptx pyproject.toml
git commit -m "feat(batch): add format converters (docx, pptx, passthrough)"
```

---

## Task 4: Implement stager (zip extract, encoding fix, format dispatch)

**Files:**
- Create: `src/rufino/engine/process/batch/stager.py`
- Test: `tests/test_batch_stager.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_batch_stager.py`:

```python
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
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/test_batch_stager.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement stager.py**

Create `src/rufino/engine/process/batch/stager.py`:

```python
"""Stage a raw corpus (ZIP or directory) into the run's inbox.

Files are organised into groups (the top-level directory each one was under).
Markdown / txt / pdf pass through verbatim; docx / pptx are converted to
markdown; legacy formats (.doc, .ppt) and unknown extensions are skipped
with a warning. ZIP filenames that look mis-encoded (cp437 from Windows
tooling) are reinterpreted as utf-8.
"""
import logging
import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from rufino.engine.process.batch.converters import convert_to_markdown
from rufino.engine.process.batch.errors import (
    ConversionError,
    StagingError,
    UnsupportedFormatError,
)


log = logging.getLogger(__name__)


PASSTHROUGH_EXTS = {".md", ".txt", ".pdf"}
CONVERTIBLE_EXTS = {".docx", ".pptx"}


@dataclass
class StagedCorpus:
    groups: dict[str, list[Path]] = field(default_factory=dict)
    skipped: list[Path] = field(default_factory=list)


def _fix_zip_name(name: str) -> str:
    try:
        return name.encode("cp437").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return name


def _extract_zip(zip_path: Path, dest: Path) -> None:
    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as e:
        raise StagingError(f"corrupt zip {zip_path}: {e}") from e
    with zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            corrected = _fix_zip_name(info.filename)
            target = dest / corrected
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)


def _group_for(file: Path, corpus_root: Path) -> str:
    rel = file.relative_to(corpus_root)
    parts = rel.parts
    return parts[0] if len(parts) > 1 else "_root"


def _stage_one_file(src_file: Path, inbox_group_dir: Path, skipped: list[Path]) -> Path | None:
    suffix = src_file.suffix.lower()
    inbox_group_dir.mkdir(parents=True, exist_ok=True)
    if suffix in PASSTHROUGH_EXTS:
        target = inbox_group_dir / src_file.name
        shutil.copy2(src_file, target)
        return target
    if suffix in CONVERTIBLE_EXTS:
        try:
            md = convert_to_markdown(src_file)
        except (ConversionError, UnsupportedFormatError) as e:
            log.warning("skipping %s: %s", src_file, e)
            skipped.append(src_file)
            return None
        target = inbox_group_dir / (src_file.stem + ".md")
        target.write_text(md, encoding="utf-8")
        return target
    log.warning("skipping unsupported format %s", src_file)
    skipped.append(src_file)
    return None


def stage_corpus(source: Path, run_dir: Path) -> StagedCorpus:
    """Stage a corpus (ZIP or directory) under <run_dir>/inbox/<group>/.

    Returns a StagedCorpus mapping group → list of staged Paths inside run_dir.
    """
    corpus_root: Path
    if source.is_file() and source.suffix.lower() == ".zip":
        extracted_temp = run_dir / "_extracted"
        extracted_temp.mkdir(parents=True, exist_ok=True)
        _extract_zip(source, extracted_temp)
        corpus_root = extracted_temp
    elif source.is_dir():
        corpus_root = source
    else:
        raise StagingError(f"source {source!r} must be a directory or .zip file")

    inbox_root = run_dir / "inbox"
    inbox_root.mkdir(parents=True, exist_ok=True)

    staged = StagedCorpus()
    for file in sorted(corpus_root.rglob("*")):
        if not file.is_file():
            continue
        group = _group_for(file, corpus_root)
        inbox_group = inbox_root / group
        target = _stage_one_file(file, inbox_group, staged.skipped)
        if target is not None:
            staged.groups.setdefault(group, []).append(target)
    return staged
```

- [ ] **Step 4: Run to confirm pass**

Run: `pytest tests/test_batch_stager.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/rufino/engine/process/batch/stager.py tests/test_batch_stager.py
git commit -m "feat(batch): add stager (zip/dir → run inbox with conversion + encoding fix)"
```

---

## Task 5: Implement planner (adaptive batching)

**Files:**
- Create: `src/rufino/engine/process/batch/planner.py`
- Test: `tests/test_batch_planner.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_batch_planner.py`:

```python
import json
from pathlib import Path

import pytest

from rufino.engine.process.batch.planner import (
    Plan,
    WorkerAssignment,
    build_plan,
)
from rufino.engine.process.batch.stager import StagedCorpus


def _fake_paths(group: str, n: int, tmp_path: Path) -> list[Path]:
    out = []
    for i in range(n):
        p = tmp_path / "inbox" / group / f"note-{i:03d}.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# n\n")
        out.append(p)
    return out


def test_single_small_group_yields_one_worker(tmp_path):
    notes = _fake_paths("math", 3, tmp_path)
    staged = StagedCorpus(groups={"math": notes})
    plan = build_plan(staged, run_id="r1", adapter_dir="/a", batch_size=10)
    assert len(plan.workers) == 1
    assert plan.workers[0].group == "math"
    assert plan.workers[0].notes == tuple(notes)


def test_group_above_batch_size_splits(tmp_path):
    notes = _fake_paths("math", 25, tmp_path)
    staged = StagedCorpus(groups={"math": notes})
    plan = build_plan(staged, run_id="r1", adapter_dir="/a", batch_size=10)
    assert len(plan.workers) == 3
    sizes = [len(w.notes) for w in plan.workers]
    assert sizes == [10, 10, 5]
    assert all(w.group == "math" for w in plan.workers)


def test_multiple_groups_independent(tmp_path):
    a = _fake_paths("math", 4, tmp_path)
    b = _fake_paths("hist", 12, tmp_path)
    staged = StagedCorpus(groups={"math": a, "hist": b})
    plan = build_plan(staged, run_id="r1", adapter_dir="/a", batch_size=10)
    assert len(plan.workers) == 3
    by_group: dict[str, list] = {}
    for w in plan.workers:
        by_group.setdefault(w.group, []).append(w)
    assert len(by_group["math"]) == 1
    assert len(by_group["hist"]) == 2


def test_worker_ids_are_unique_and_stable(tmp_path):
    notes = _fake_paths("math", 25, tmp_path)
    plan = build_plan(
        StagedCorpus(groups={"math": notes}),
        run_id="r1", adapter_dir="/a", batch_size=10,
    )
    ids = [w.worker_id for w in plan.workers]
    assert ids == ["w001", "w002", "w003"]


def test_empty_corpus_yields_empty_plan(tmp_path):
    plan = build_plan(StagedCorpus(), run_id="r1", adapter_dir="/a", batch_size=10)
    assert plan.workers == ()


def test_plan_serialises_to_json(tmp_path):
    notes = _fake_paths("math", 2, tmp_path)
    plan = build_plan(
        StagedCorpus(groups={"math": notes}),
        run_id="r1", adapter_dir="/a", batch_size=10,
    )
    s = plan.to_json()
    parsed = json.loads(s)
    assert parsed["run_id"] == "r1"
    assert parsed["adapter_dir"] == "/a"
    assert len(parsed["workers"]) == 1
    assert parsed["workers"][0]["worker_id"] == "w001"
    assert len(parsed["workers"][0]["notes"]) == 2
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/test_batch_planner.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement planner.py**

Create `src/rufino/engine/process/batch/planner.py`:

```python
"""Build an execution Plan from a StagedCorpus.

Adaptive batching: each group gets 1 worker if it has <= batch_size notes,
otherwise it is split into ceil(n / batch_size) consecutive chunks.
"""
import json
import math
from dataclasses import dataclass
from pathlib import Path

from rufino.engine.process.batch.stager import StagedCorpus


@dataclass(frozen=True)
class WorkerAssignment:
    worker_id: str
    group: str
    notes: tuple[Path, ...]


@dataclass(frozen=True)
class Plan:
    run_id: str
    adapter_dir: str
    workers: tuple[WorkerAssignment, ...]

    def to_json(self) -> str:
        return json.dumps(
            {
                "run_id": self.run_id,
                "adapter_dir": self.adapter_dir,
                "workers": [
                    {
                        "worker_id": w.worker_id,
                        "group": w.group,
                        "notes": [str(p) for p in w.notes],
                    }
                    for w in self.workers
                ],
            },
            indent=2,
        )


def build_plan(
    staged: StagedCorpus,
    *,
    run_id: str,
    adapter_dir: str,
    batch_size: int,
) -> Plan:
    if batch_size < 1:
        raise ValueError(f"batch_size must be >= 1, got {batch_size}")

    workers: list[WorkerAssignment] = []
    counter = 1
    for group in sorted(staged.groups):
        notes = list(staged.groups[group])
        if not notes:
            continue
        if len(notes) <= batch_size:
            workers.append(WorkerAssignment(
                worker_id=f"w{counter:03d}",
                group=group,
                notes=tuple(notes),
            ))
            counter += 1
            continue
        chunks = math.ceil(len(notes) / batch_size)
        for chunk_idx in range(chunks):
            slice_ = notes[chunk_idx * batch_size : (chunk_idx + 1) * batch_size]
            workers.append(WorkerAssignment(
                worker_id=f"w{counter:03d}",
                group=group,
                notes=tuple(slice_),
            ))
            counter += 1
    return Plan(run_id=run_id, adapter_dir=adapter_dir, workers=tuple(workers))
```

- [ ] **Step 4: Run to confirm pass**

Run: `pytest tests/test_batch_planner.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/rufino/engine/process/batch/planner.py tests/test_batch_planner.py
git commit -m "feat(batch): add planner with adaptive batching by group"
```

---

## Task 6: Implement worker prompt builder

**Files:**
- Create: `src/rufino/engine/process/batch/worker_prompt.py`
- Test: `tests/test_batch_worker_prompt.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_batch_worker_prompt.py`:

```python
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
    )

    assert "worker de Rufino" in prompt
    assert str(notes[0]) in prompt
    assert str(staging_dir) in prompt
    assert "augmented/<slug>.md" in prompt
    assert "deltas/<slug>.json" in prompt
    assert "ASK-USER" in prompt
    assert "be rigorous about triples." in prompt
    assert "ask-rufino-my-vault" in prompt


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
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/test_batch_worker_prompt.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement worker_prompt.py**

Create `src/rufino/engine/process/batch/worker_prompt.py`:

```python
"""Construct the system prompt handed to each Claude worker subprocess.

Three concatenated blocks (preamble + adapter prompt + vault context),
exactly as described in spec §2.4.
"""
from pathlib import Path

from rufino.engine.process.batch.planner import WorkerAssignment
from rufino.engine.process.manifest import WorkerAdapterManifest


_PREAMBLE_TEMPLATE = """\
Sos un worker de Rufino procesando notas en batch.

Tu asignación (worker_id={worker_id}, grupo={group}):

{note_lines}

Staging dir (escribí AQUÍ y nada más fuera de acá): {staging_dir}

Para CADA nota tenés que producir dos archivos en el staging dir:

  - `augmented/<slug>.md` — la nota augmentada con frontmatter YAML cumpliendo
    el output_schema del adapter, body en markdown, triples en el vocabulario
    permitido, tags en los ejes declarados.
  - `deltas/<slug>.json` — un JSON con los cambios:
    {{
      "note_slug": "<slug>",
      "tags_added": [...],
      "triples_emitted": [{{"s":"...","r":"...","o":"..."}}, ...],
      "concepts_referenced": [...],
      "concepts_promoted": [...],
      "wikilinks_added": [...],
      "qa_opened": [],
      "warnings": []
    }}

Si la nota dispara un Q&A trigger del adapter, NO escribas augmented/<slug>.md
ni deltas/<slug>.json para esa nota. Escribí en su lugar:

  - `pending/<slug>.json` con este formato:
    {{
      "origin": "process-batch",
      "run_id": "{run_id}",
      "worker_id": "{worker_id}",
      "pending_note": "<slug>",
      "input_path": "<input-path-relative-to-vault>",
      "trigger": "<qa_trigger-name>",
      "context": "<resumen para retomar tras la respuesta>",
      "question": "<la pregunta concreta al usuario>"
    }}

ASK-USER marker (usalo SOLO cuando un qa_trigger del adapter aplique).

Tipos de errores típicos a evitar:
  - triples con relaciones fuera del vocabulario (te las rechazo y te hago retry)
  - frontmatter sin los required fields del output_schema
  - destination_path con caracteres ilegales / escapes a otro vault

Cuando termines, no contestes nada al stdout — todo el resultado son archivos
en el staging.
"""

_VAULT_CONTEXT_TEMPLATE = """\

Tenés acceso al MCP `ask-rufino-{slug}`. Usalo para:
  - buscar conceptos ya promovidos en el vault (evitá duplicarlos)
  - detectar wikilinks naturales (notas relacionadas)
  - resolver contextos ambiguos antes de inventar
{concepts_block}
"""


def build_worker_system_prompt(
    *,
    manifest: WorkerAdapterManifest,
    adapter_prompt_text: str,
    assignment: WorkerAssignment,
    vault_slug: str,
    staging_dir: Path,
    vault_concepts_top_n: list[str],
    run_id: str = "",
) -> str:
    note_lines = "\n".join(f"  - {p}" for p in assignment.notes)
    preamble = _PREAMBLE_TEMPLATE.format(
        worker_id=assignment.worker_id,
        group=assignment.group,
        note_lines=note_lines,
        staging_dir=staging_dir,
        run_id=run_id,
    )
    concepts_block = ""
    if vault_concepts_top_n:
        bullets = "\n".join(f"  - {c}" for c in vault_concepts_top_n)
        concepts_block = (
            "\nConceptos ya presentes en el vault (preferí reusar):\n"
            f"{bullets}\n"
        )
    vault_context = _VAULT_CONTEXT_TEMPLATE.format(
        slug=vault_slug, concepts_block=concepts_block,
    )
    return f"{preamble}\n---\n{adapter_prompt_text}\n---\n{vault_context}"


_RETRY_TEMPLATE = """

RETRY

Procesaste esta nota antes y el output no pasó validación. Errores específicos:

{error_lines}

El input original sigue siendo el mismo. Rehacelo corrigiendo SOLO los puntos
listados; el resto del trabajo está OK y no hace falta retocar.
"""


def build_retry_appendix(errors: list[str]) -> str:
    lines = "\n".join(f"  - {e}" for e in errors)
    return _RETRY_TEMPLATE.format(error_lines=lines)
```

- [ ] **Step 4: Run to confirm pass**

Run: `pytest tests/test_batch_worker_prompt.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/rufino/engine/process/batch/worker_prompt.py tests/test_batch_worker_prompt.py
git commit -m "feat(batch): add worker system-prompt + retry-appendix builders"
```

---

## Task 7: Implement the claude-runner helper + fake-claude test fixture

The runner helper wraps a blocking `subprocess.run` (argv-list, no shell) inside `asyncio.to_thread`. This single helper is the only place in the codebase that invokes the `claude` binary directly; every other module calls it.

**Files:**
- Create: `src/rufino/engine/process/batch/runner_helper.py`
- Create: `tests/fixtures/fake_claude/claude` (executable Python script)
- Create: `tests/fixtures/fake_claude/README.md`
- Test: `tests/test_batch_runner_helper.py` (new — exercises the helper + fixture together)

- [ ] **Step 1: Write the failing test**

Create `tests/test_batch_runner_helper.py`:

```python
import asyncio
import json
import os
from pathlib import Path

import pytest

from rufino.engine.process.batch.runner_helper import (
    ClaudeResult,
    run_claude,
)


FAKE_DIR = Path("tests/fixtures/fake_claude").resolve()


@pytest.fixture(autouse=True)
def _fake_on_path(monkeypatch):
    monkeypatch.setenv("PATH", str(FAKE_DIR) + os.pathsep + os.environ["PATH"])


def test_run_claude_writes_outputs(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "augment")
    note = tmp_path / "n.md"
    note.write_text("# n\n")
    monkeypatch.setenv("FAKE_CLAUDE_NOTES", str(note))

    result = asyncio.run(run_claude(
        argv=["claude", "-p", "--system-prompt", "x", "--", "go"],
        cwd=tmp_path,
        env=os.environ.copy(),
        timeout_seconds=30.0,
    ))
    assert isinstance(result, ClaudeResult)
    assert result.exit_code == 0
    assert (tmp_path / "augmented" / "n.md").exists()
    assert (tmp_path / "deltas" / "n.json").exists()


def test_run_claude_timeout(tmp_path, monkeypatch):
    """Simulate timeout: fake_claude in 'hang' mode never returns."""
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "hang")

    result = asyncio.run(run_claude(
        argv=["claude", "-p"],
        cwd=tmp_path,
        env=os.environ.copy(),
        timeout_seconds=0.5,
    ))
    assert result.exit_code == 124  # timeout sentinel


def test_run_claude_session_expired(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "session_expired")
    result = asyncio.run(run_claude(
        argv=["claude", "-p"],
        cwd=tmp_path,
        env=os.environ.copy(),
        timeout_seconds=30.0,
    ))
    assert result.exit_code == 41
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/test_batch_runner_helper.py -v`
Expected: FAIL — helper + fixture missing.

- [ ] **Step 3: Implement the fake `claude` fixture**

Create `tests/fixtures/fake_claude/claude` (mark `chmod +x`):

```python
#!/usr/bin/env python3
"""Fake `claude -p` for testing rufino process-batch.

Driven by env vars:
  FAKE_CLAUDE_MODE: augment | augment_bad | qa | session_expired | empty | hang
  FAKE_CLAUDE_NOTES: newline- or os.pathsep-separated absolute note paths.

Writes outputs to cwd:
  augmented/<slug>.md, deltas/<slug>.json (modes augment / augment_bad)
  pending/<slug>.json (mode qa)
Exits 41 (session_expired)
Hangs forever (mode hang) — caller must time it out.
"""
import json
import os
import sys
import time
from pathlib import Path


SESSION_EXPIRED_EXIT = 41


def _notes_from_env() -> list[Path]:
    raw = os.environ.get("FAKE_CLAUDE_NOTES", "")
    if not raw:
        return []
    parts = raw.replace("\n", os.pathsep).split(os.pathsep)
    return [Path(p) for p in parts if p.strip()]


def _augment(slug: str, body: str, *, valid: bool):
    if valid:
        fm = (
            "---\n"
            f"title: {slug}\n"
            f"materia: fake\n"
            "tags: [materia/fake]\n"
            "triples:\n"
            "  - {s: \"thing\", r: \"tema-de\", o: \"fake\"}\n"
            "---\n"
        )
        delta = {
            "note_slug": slug,
            "tags_added": ["materia/fake"],
            "triples_emitted": [{"s": "thing", "r": "tema-de", "o": "fake"}],
            "concepts_referenced": ["thing"],
            "concepts_promoted": [],
            "wikilinks_added": [],
            "qa_opened": [],
            "warnings": [],
        }
    else:
        fm = (
            "---\n"
            f"materia: fake\n"
            "tags: []\n"
            "triples:\n"
            "  - {s: \"thing\", r: \"INVALID-relation\", o: \"fake\"}\n"
            "---\n"
        )
        delta = {
            "note_slug": slug,
            "tags_added": [],
            "triples_emitted": [{"s": "thing", "r": "INVALID-relation", "o": "fake"}],
            "concepts_referenced": [],
            "concepts_promoted": [],
            "wikilinks_added": [],
            "qa_opened": [],
            "warnings": [],
        }
    return fm + body, delta


def main() -> int:
    mode = os.environ.get("FAKE_CLAUDE_MODE", "augment")
    if mode == "session_expired":
        sys.stderr.write("fake-claude: session expired\n")
        return SESSION_EXPIRED_EXIT
    if mode == "empty":
        return 0
    if mode == "hang":
        time.sleep(3600)
        return 0

    notes = _notes_from_env()
    cwd = Path.cwd()

    if mode == "qa":
        (cwd / "pending").mkdir(exist_ok=True)
        for note in notes:
            slug = note.stem
            pending = {
                "origin": "process-batch",
                "run_id": os.environ.get("FAKE_CLAUDE_RUN_ID", "test-run"),
                "worker_id": os.environ.get("FAKE_CLAUDE_WORKER_ID", "w001"),
                "pending_note": slug,
                "input_path": str(note),
                "trigger": "fake_trigger",
                "context": "fake context",
                "question": f"What about {slug}?",
            }
            (cwd / "pending" / f"{slug}.json").write_text(json.dumps(pending, indent=2))
        return 0

    valid = (mode == "augment")
    (cwd / "augmented").mkdir(exist_ok=True)
    (cwd / "deltas").mkdir(exist_ok=True)
    for note in notes:
        slug = note.stem
        body = f"\n# {slug}\nfake augmented body\n"
        md, delta = _augment(slug, body, valid=valid)
        (cwd / "augmented" / f"{slug}.md").write_text(md)
        (cwd / "deltas" / f"{slug}.json").write_text(json.dumps(delta, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Run: `chmod +x tests/fixtures/fake_claude/claude`

Create `tests/fixtures/fake_claude/README.md`:

```markdown
# fake_claude

Replaces the real `claude` CLI for testing `rufino process-batch`.

Tests put this dir on PATH (`PATH = fake_claude_dir + os.pathsep + PATH`), then
spawn workers as usual. Mode is selected via `FAKE_CLAUDE_MODE` env var; notes
to process are passed via `FAKE_CLAUDE_NOTES` (newline- or os.pathsep-separated
absolute paths).

Modes:
- `augment` (default): valid augmented/<slug>.md + deltas/<slug>.json
- `augment_bad`: outputs that fail validation
- `qa`: pending/<slug>.json (Q&A path)
- `session_expired`: exit 41
- `empty`: exit 0, no outputs
- `hang`: sleep forever (force a timeout in the caller)
```

- [ ] **Step 4: Implement runner_helper.py**

Create `src/rufino/engine/process/batch/runner_helper.py`:

```python
"""Single chokepoint for invoking the `claude` binary.

We use `subprocess.run` with argv passed as a list (no shell, no injection
surface) and wrap it in `asyncio.to_thread` so callers can fan many workers
out under an asyncio.Semaphore without giving up async scheduling.

This is the only module that talks to subprocess.run for `claude` —
everything else calls run_claude().
"""
import asyncio
import subprocess
from dataclasses import dataclass
from pathlib import Path


TIMEOUT_EXIT_CODE = 124


@dataclass(frozen=True)
class ClaudeResult:
    exit_code: int
    stdout: str = ""
    stderr: str = ""


def _run_blocking(
    argv: list[str], cwd: Path, env: dict, timeout_seconds: float,
) -> ClaudeResult:
    try:
        completed = subprocess.run(
            argv,
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        return ClaudeResult(
            exit_code=TIMEOUT_EXIT_CODE,
            stderr=f"timed out after {timeout_seconds}s: {e}",
        )
    return ClaudeResult(
        exit_code=completed.returncode,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
    )


async def run_claude(
    *,
    argv: list[str],
    cwd: Path,
    env: dict,
    timeout_seconds: float,
) -> ClaudeResult:
    """Run a claude subprocess to completion. Returns ClaudeResult always —
    callers inspect exit_code for non-zero / timeout (124) / auth-fail (41).
    """
    return await asyncio.to_thread(
        _run_blocking, argv, cwd, env, timeout_seconds,
    )
```

- [ ] **Step 5: Run to confirm pass**

Run: `pytest tests/test_batch_runner_helper.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/rufino/engine/process/batch/runner_helper.py tests/fixtures/fake_claude/ tests/test_batch_runner_helper.py
git commit -m "feat(batch): add run_claude helper + fake claude test fixture"
```

---

## Task 8: Implement dispatcher (parallel worker spawning)

**Files:**
- Create: `src/rufino/engine/process/batch/dispatcher.py`
- Test: `tests/test_batch_dispatcher.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_batch_dispatcher.py`:

```python
import asyncio
import os
from pathlib import Path

import pytest

from rufino.engine.process.batch.dispatcher import (
    DispatchOutcome,
    WorkerOutcome,
    dispatch,
)
from rufino.engine.process.batch.errors import WorkerSessionExpiredError
from rufino.engine.process.batch.planner import WorkerAssignment, Plan


FAKE_DIR = Path("tests/fixtures/fake_claude").resolve()


@pytest.fixture(autouse=True)
def _path_with_fake_claude(monkeypatch):
    monkeypatch.setenv("PATH", str(FAKE_DIR) + os.pathsep + os.environ["PATH"])


def _staged_note(tmp_path: Path, group: str, slug: str) -> Path:
    p = tmp_path / "inbox" / group / f"{slug}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"# {slug}\n")
    return p


def _plan_with(notes_by_worker: dict[str, list[Path]]) -> Plan:
    workers = tuple(
        WorkerAssignment(worker_id=wid, group="g", notes=tuple(ns))
        for wid, ns in notes_by_worker.items()
    )
    return Plan(run_id="r1", adapter_dir="/a", workers=workers)


def test_dispatch_writes_outputs(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "augment")
    n1 = _staged_note(tmp_path, "g", "n1")
    n2 = _staged_note(tmp_path, "g", "n2")
    plan = _plan_with({"w001": [n1, n2]})

    outcome = asyncio.run(dispatch(
        plan=plan, run_dir=tmp_path,
        system_prompt_for=lambda a: f"prompt for {a.worker_id}",
        vault_slug="v", max_workers=2, timeout_seconds=30,
    ))
    assert isinstance(outcome, DispatchOutcome)
    assert len(outcome.workers) == 1
    assert outcome.workers[0].exit_code == 0

    staging = tmp_path / "workers" / "w001"
    assert (staging / "augmented" / "n1.md").exists()
    assert (staging / "augmented" / "n2.md").exists()
    assert (staging / "deltas" / "n1.json").exists()


def test_dispatch_parallel_smoke(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "augment")
    plan = _plan_with({
        f"w{i:03d}": [_staged_note(tmp_path, "g", f"n{i}")]
        for i in range(1, 5)
    })
    outcome = asyncio.run(dispatch(
        plan=plan, run_dir=tmp_path,
        system_prompt_for=lambda a: "p", vault_slug="v",
        max_workers=2, timeout_seconds=30,
    ))
    assert len(outcome.workers) == 4
    assert all(w.exit_code == 0 for w in outcome.workers)


def test_dispatch_session_expired_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "session_expired")
    n = _staged_note(tmp_path, "g", "n1")
    plan = _plan_with({"w001": [n]})
    with pytest.raises(WorkerSessionExpiredError):
        asyncio.run(dispatch(
            plan=plan, run_dir=tmp_path,
            system_prompt_for=lambda a: "p", vault_slug="v",
            max_workers=1, timeout_seconds=30,
        ))


def test_dispatch_empty_outputs_ok(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "empty")
    n = _staged_note(tmp_path, "g", "n1")
    plan = _plan_with({"w001": [n]})
    outcome = asyncio.run(dispatch(
        plan=plan, run_dir=tmp_path,
        system_prompt_for=lambda a: "p", vault_slug="v",
        max_workers=1, timeout_seconds=30,
    ))
    assert outcome.workers[0].exit_code == 0
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/test_batch_dispatcher.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement dispatcher.py**

Create `src/rufino/engine/process/batch/dispatcher.py`:

```python
"""Spawn `claude` worker subprocesses for each WorkerAssignment in a plan.

Workers run via `run_claude` (see runner_helper.py) under an asyncio
semaphore. The fake_claude test fixture mimics the real `claude -p` calling
convention to exercise this code without spending tokens.
"""
import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from rufino.engine.process.batch.errors import (
    DispatchError,
    WorkerSessionExpiredError,
)
from rufino.engine.process.batch.planner import Plan, WorkerAssignment
from rufino.engine.process.batch.runner_helper import (
    ClaudeResult,
    TIMEOUT_EXIT_CODE,
    run_claude,
)


SESSION_EXPIRED_EXIT_CODE = 41


@dataclass(frozen=True)
class WorkerOutcome:
    worker_id: str
    exit_code: int
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True)
class DispatchOutcome:
    workers: tuple[WorkerOutcome, ...] = field(default_factory=tuple)


def build_argv(*, system_prompt: str, staging_dir: Path, vault_slug: str) -> list[str]:
    return [
        "claude",
        "-p",
        "--system-prompt", system_prompt,
        "--allowedTools",
        f"Read,Write,Glob,mcp__ask-rufino-{vault_slug}__*",
        "--cwd", str(staging_dir),
        "--",
        "Procesá las notas listadas en assignment.json siguiendo el system prompt.",
    ]


async def _run_one(
    assignment: WorkerAssignment,
    *,
    run_dir: Path,
    system_prompt: str,
    vault_slug: str,
    timeout_seconds: float,
) -> WorkerOutcome:
    staging_dir = run_dir / "workers" / assignment.worker_id
    staging_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["FAKE_CLAUDE_NOTES"] = os.pathsep.join(str(p) for p in assignment.notes)
    env["FAKE_CLAUDE_RUN_ID"] = run_dir.name
    env["FAKE_CLAUDE_WORKER_ID"] = assignment.worker_id

    argv = build_argv(
        system_prompt=system_prompt, staging_dir=staging_dir,
        vault_slug=vault_slug,
    )

    result: ClaudeResult = await run_claude(
        argv=argv, cwd=staging_dir, env=env, timeout_seconds=timeout_seconds,
    )

    if result.exit_code == SESSION_EXPIRED_EXIT_CODE:
        raise WorkerSessionExpiredError(
            "Tu sesión Claude está expirada. Corré `claude login` y reintentá."
        )

    return WorkerOutcome(
        worker_id=assignment.worker_id,
        exit_code=result.exit_code,
        stdout=result.stdout, stderr=result.stderr,
    )


async def dispatch(
    *,
    plan: Plan,
    run_dir: Path,
    system_prompt_for: Callable[[WorkerAssignment], str],
    vault_slug: str,
    max_workers: int,
    timeout_seconds: float = 300.0,
) -> DispatchOutcome:
    """Run all workers in plan.workers, bounded by max_workers concurrent.

    Raises WorkerSessionExpiredError immediately if any worker reports an
    expired session. Other failures (timeouts, non-zero exits, empty outputs)
    are reflected in WorkerOutcome and left for the validator.
    """
    if not plan.workers:
        return DispatchOutcome(workers=())

    sem = asyncio.Semaphore(max(1, max_workers))

    async def _guarded(a: WorkerAssignment) -> WorkerOutcome:
        async with sem:
            return await _run_one(
                a, run_dir=run_dir,
                system_prompt=system_prompt_for(a),
                vault_slug=vault_slug,
                timeout_seconds=timeout_seconds,
            )

    outcomes = await asyncio.gather(*(_guarded(a) for a in plan.workers))
    return DispatchOutcome(workers=tuple(outcomes))
```

- [ ] **Step 4: Run to confirm pass**

Run: `pytest tests/test_batch_dispatcher.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/rufino/engine/process/batch/dispatcher.py tests/test_batch_dispatcher.py
git commit -m "feat(batch): add parallel dispatcher for claude workers"
```

---

## Task 9: Implement validator

**Files:**
- Create: `src/rufino/engine/process/batch/validator.py`
- Test: `tests/test_batch_validator.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_batch_validator.py`:

```python
import json
from pathlib import Path

import pytest

from rufino.engine.process.batch.validator import (
    NoteValidation,
    ValidationReport,
    validate_worker_output,
)
from rufino.engine.process.manifest import parse_worker_manifest


_MANIFEST = """
adapter_name: x
note_type: x
applies_when: {source_dir: inbox/, matches_pattern: ["*.md"]}
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
destination_path: "x/{slug}.md"
"""


def _write_worker_output(staging, slug, frontmatter, delta):
    aug = staging / "augmented"
    deltas = staging / "deltas"
    aug.mkdir(parents=True, exist_ok=True)
    deltas.mkdir(parents=True, exist_ok=True)
    (aug / f"{slug}.md").write_text(frontmatter + "\n# body\n")
    if delta is not None:
        (deltas / f"{slug}.json").write_text(json.dumps(delta))


def test_valid_output_passes(tmp_path):
    manifest = parse_worker_manifest(_MANIFEST)
    fm = (
        "---\n"
        "title: ok\n"
        "materia: math\n"
        "tags: [materia/math]\n"
        "triples:\n"
        "  - {s: \"a\", r: \"tema-de\", o: \"b\"}\n"
        "---"
    )
    _write_worker_output(tmp_path, "good", fm, {
        "note_slug": "good", "tags_added": [], "triples_emitted": [],
        "concepts_referenced": [], "concepts_promoted": [],
        "wikilinks_added": [], "qa_opened": [], "warnings": [],
    })
    report = validate_worker_output(tmp_path, manifest)
    assert isinstance(report, ValidationReport)
    assert len(report.passed) == 1
    assert report.passed[0].slug == "good"
    assert report.failed == ()


def test_missing_required_field_flags(tmp_path):
    manifest = parse_worker_manifest(_MANIFEST)
    fm = "---\nmateria: math\n---"
    _write_worker_output(tmp_path, "bad", fm, {"note_slug": "bad"})
    report = validate_worker_output(tmp_path, manifest)
    assert len(report.failed) == 1
    assert any("title" in e for e in report.failed[0].errors)


def test_out_of_vocab_triple_flags(tmp_path):
    manifest = parse_worker_manifest(_MANIFEST)
    fm = (
        "---\n"
        "title: x\n"
        "materia: math\n"
        "triples:\n"
        "  - {s: \"a\", r: \"INVALID\", o: \"b\"}\n"
        "---"
    )
    _write_worker_output(tmp_path, "bad", fm, {"note_slug": "bad"})
    report = validate_worker_output(tmp_path, manifest)
    assert len(report.failed) == 1
    assert any("INVALID" in e for e in report.failed[0].errors)


def test_missing_delta_flags(tmp_path):
    manifest = parse_worker_manifest(_MANIFEST)
    fm = "---\ntitle: ok\nmateria: math\n---"
    _write_worker_output(tmp_path, "nodelta", fm, delta=None)
    report = validate_worker_output(tmp_path, manifest)
    assert len(report.failed) == 1
    assert any("delta" in e.lower() for e in report.failed[0].errors)


def test_malformed_delta_flags(tmp_path):
    manifest = parse_worker_manifest(_MANIFEST)
    aug = tmp_path / "augmented"
    deltas = tmp_path / "deltas"
    aug.mkdir(parents=True)
    deltas.mkdir(parents=True)
    (aug / "x.md").write_text("---\ntitle: t\nmateria: m\n---\n")
    (deltas / "x.json").write_text("{not: json}")
    report = validate_worker_output(tmp_path, manifest)
    assert len(report.failed) == 1
    assert any("json" in e.lower() for e in report.failed[0].errors)


def test_pending_only_is_skipped(tmp_path):
    manifest = parse_worker_manifest(_MANIFEST)
    pending = tmp_path / "pending"
    pending.mkdir()
    (pending / "x.json").write_text("{}")
    report = validate_worker_output(tmp_path, manifest)
    assert report.passed == ()
    assert report.failed == ()
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/test_batch_validator.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement validator.py**

Create `src/rufino/engine/process/batch/validator.py`:

```python
"""Post-hoc validation of worker outputs against the adapter manifest."""
import json
from dataclasses import dataclass, field
from pathlib import Path

from rufino.engine.process.helpers.frontmatter import (
    parse_frontmatter,
    validate_against_schema,
)
from rufino.engine.process.helpers.triples import (
    extract_triples,
    validate_triples_against_vocab,
)
from rufino.engine.process.manifest import WorkerAdapterManifest


@dataclass(frozen=True)
class NoteValidation:
    slug: str
    augmented_path: Path
    delta_path: Path | None
    errors: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class ValidationReport:
    passed: tuple[NoteValidation, ...] = field(default_factory=tuple)
    failed: tuple[NoteValidation, ...] = field(default_factory=tuple)


def _validate_one(
    augmented_path: Path,
    delta_path: Path,
    manifest: WorkerAdapterManifest,
) -> NoteValidation:
    errors: list[str] = []
    slug = augmented_path.stem

    try:
        text = augmented_path.read_text(encoding="utf-8")
        fm, _body = parse_frontmatter(text)
    except Exception as e:
        return NoteValidation(
            slug=slug, augmented_path=augmented_path, delta_path=None,
            errors=(f"failed to parse frontmatter: {e}",),
        )

    try:
        validate_against_schema(fm, manifest.output_schema)
    except Exception as e:
        errors.append(f"schema violation: {e}")

    try:
        triples = extract_triples(fm)
        validate_triples_against_vocab(triples, set(manifest.triple_vocabulary))
    except Exception as e:
        errors.append(f"triple validation: {e}")

    if not delta_path.exists():
        errors.append("delta json file missing")
    else:
        try:
            json.loads(delta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            errors.append(f"delta json parse error: {e}")

    return NoteValidation(
        slug=slug, augmented_path=augmented_path,
        delta_path=delta_path if delta_path.exists() else None,
        errors=tuple(errors),
    )


def validate_worker_output(
    staging_dir: Path,
    manifest: WorkerAdapterManifest,
) -> ValidationReport:
    aug_dir = staging_dir / "augmented"
    delta_dir = staging_dir / "deltas"
    passed: list[NoteValidation] = []
    failed: list[NoteValidation] = []
    if not aug_dir.exists():
        return ValidationReport()
    for aug_path in sorted(aug_dir.glob("*.md")):
        delta_path = delta_dir / f"{aug_path.stem}.json"
        result = _validate_one(aug_path, delta_path, manifest)
        (passed if result.passed else failed).append(result)
    return ValidationReport(passed=tuple(passed), failed=tuple(failed))
```

- [ ] **Step 4: Run to confirm pass**

Run: `pytest tests/test_batch_validator.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/rufino/engine/process/batch/validator.py tests/test_batch_validator.py
git commit -m "feat(batch): add post-hoc validator for worker outputs"
```

---

## Task 10: Implement retry logic

**Files:**
- Create: `src/rufino/engine/process/batch/retry.py`
- Test: `tests/test_batch_retry.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_batch_retry.py`:

```python
import asyncio
import json
import os
from pathlib import Path

import pytest

from rufino.engine.process.batch.planner import WorkerAssignment
from rufino.engine.process.batch.retry import retry_failed
from rufino.engine.process.batch.validator import NoteValidation, ValidationReport
from rufino.engine.process.manifest import parse_worker_manifest


FAKE_DIR = Path("tests/fixtures/fake_claude").resolve()


_MANIFEST = """
adapter_name: x
note_type: x
applies_when: {source_dir: inbox/, matches_pattern: ["*.md"]}
llm: sonnet
mode_default: full
output_schema:
  required:
    title: string
    materia: string
triple_vocabulary:
  - tema-de
tag_axes:
  - axis: materia
    format: "materia/{slug}"
destination_path: "x/{slug}.md"
"""


@pytest.fixture(autouse=True)
def _fake_claude_on_path(monkeypatch):
    monkeypatch.setenv("PATH", str(FAKE_DIR) + os.pathsep + os.environ["PATH"])


def _setup_failed_note(staging: Path, slug: str) -> NoteValidation:
    aug = staging / "augmented" / f"{slug}.md"
    aug.parent.mkdir(parents=True, exist_ok=True)
    aug.write_text("---\nmateria: x\n---\n# body\n")
    return NoteValidation(
        slug=slug, augmented_path=aug, delta_path=None,
        errors=("schema violation: missing 'title'",),
    )


def test_retry_succeeds_on_second_try(tmp_path, monkeypatch):
    manifest = parse_worker_manifest(_MANIFEST)
    note = tmp_path / "inbox" / "g" / "n1.md"
    note.parent.mkdir(parents=True)
    note.write_text("# n\n")
    staging = tmp_path / "workers" / "w001"
    failed = (_setup_failed_note(staging, "n1"),)

    monkeypatch.setenv("FAKE_CLAUDE_MODE", "augment")

    report = asyncio.run(retry_failed(
        failed=failed, manifest=manifest, adapter_prompt_text="",
        worker_assignment=WorkerAssignment(worker_id="w001", group="g", notes=(note,)),
        run_dir=tmp_path, vault_slug="v",
        max_retries=2, timeout_seconds=30,
    ))
    assert len(report.passed) == 1
    assert report.failed == ()


def test_retry_bounces_after_max_retries(tmp_path, monkeypatch):
    manifest = parse_worker_manifest(_MANIFEST)
    note = tmp_path / "inbox" / "g" / "n1.md"
    note.parent.mkdir(parents=True)
    note.write_text("# n\n")
    staging = tmp_path / "workers" / "w001"
    failed = (_setup_failed_note(staging, "n1"),)

    monkeypatch.setenv("FAKE_CLAUDE_MODE", "augment_bad")

    report = asyncio.run(retry_failed(
        failed=failed, manifest=manifest, adapter_prompt_text="",
        worker_assignment=WorkerAssignment(worker_id="w001", group="g", notes=(note,)),
        run_dir=tmp_path, vault_slug="v",
        max_retries=2, timeout_seconds=30,
    ))
    assert report.passed == ()
    assert len(report.failed) == 1
    bounced = staging / "failed" / "n1"
    assert bounced.exists()
    assert (bounced / "error.json").exists()
    err = json.loads((bounced / "error.json").read_text())
    assert err["slug"] == "n1"
    assert err["errors"]
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/test_batch_retry.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement retry.py**

Create `src/rufino/engine/process/batch/retry.py`:

```python
"""Retry loop for failed notes: re-invoke the worker for one note at a time,
with an appended RETRY block listing specific errors. After `max_retries`
fail, bounce the note to `failed/<slug>/`.
"""
import json
import os
import shutil
from pathlib import Path

from rufino.engine.process.batch.dispatcher import (
    SESSION_EXPIRED_EXIT_CODE,
    build_argv,
)
from rufino.engine.process.batch.errors import WorkerSessionExpiredError
from rufino.engine.process.batch.planner import WorkerAssignment
from rufino.engine.process.batch.runner_helper import run_claude
from rufino.engine.process.batch.validator import (
    NoteValidation,
    ValidationReport,
    _validate_one,
)
from rufino.engine.process.batch.worker_prompt import (
    build_retry_appendix,
    build_worker_system_prompt,
)
from rufino.engine.process.manifest import WorkerAdapterManifest


async def _retry_one(
    note_path: Path,
    *,
    base_prompt: str,
    appendix: str,
    staging_dir: Path,
    vault_slug: str,
    timeout_seconds: float,
) -> None:
    env = os.environ.copy()
    env["FAKE_CLAUDE_NOTES"] = str(note_path)
    argv = build_argv(
        system_prompt=base_prompt + appendix,
        staging_dir=staging_dir,
        vault_slug=vault_slug,
    )
    result = await run_claude(
        argv=argv, cwd=staging_dir, env=env, timeout_seconds=timeout_seconds,
    )
    if result.exit_code == SESSION_EXPIRED_EXIT_CODE:
        raise WorkerSessionExpiredError(
            "Tu sesión Claude está expirada. Corré `claude login` y reintentá."
        )


def _bounce_to_failed(
    staging_dir: Path, slug: str, validation: NoteValidation,
) -> None:
    failed_dir = staging_dir / "failed" / slug
    failed_dir.mkdir(parents=True, exist_ok=True)
    aug = staging_dir / "augmented" / f"{slug}.md"
    delta = staging_dir / "deltas" / f"{slug}.json"
    if aug.exists():
        shutil.copy2(aug, failed_dir / "augmented.md")
        aug.unlink()
    if delta.exists():
        shutil.copy2(delta, failed_dir / "delta.json")
        delta.unlink()
    (failed_dir / "error.json").write_text(json.dumps({
        "slug": slug,
        "errors": list(validation.errors),
    }, indent=2))


async def retry_failed(
    *,
    failed: tuple[NoteValidation, ...],
    manifest: WorkerAdapterManifest,
    adapter_prompt_text: str,
    worker_assignment: WorkerAssignment,
    run_dir: Path,
    vault_slug: str,
    max_retries: int = 2,
    timeout_seconds: float = 300.0,
) -> ValidationReport:
    staging_dir = run_dir / "workers" / worker_assignment.worker_id
    base_prompt = build_worker_system_prompt(
        manifest=manifest, adapter_prompt_text=adapter_prompt_text,
        assignment=worker_assignment, vault_slug=vault_slug,
        staging_dir=staging_dir, vault_concepts_top_n=[],
        run_id=run_dir.name,
    )
    passed: list[NoteValidation] = []
    still_failed: list[NoteValidation] = []

    for nv in failed:
        matching = [p for p in worker_assignment.notes if p.stem == nv.slug]
        if not matching:
            still_failed.append(nv)
            _bounce_to_failed(staging_dir, nv.slug, nv)
            continue
        note_path = matching[0]
        current = nv
        won = False
        for _ in range(max_retries):
            appendix = build_retry_appendix(list(current.errors))
            await _retry_one(
                note_path, base_prompt=base_prompt, appendix=appendix,
                staging_dir=staging_dir, vault_slug=vault_slug,
                timeout_seconds=timeout_seconds,
            )
            aug = staging_dir / "augmented" / f"{nv.slug}.md"
            delta = staging_dir / "deltas" / f"{nv.slug}.json"
            if not aug.exists():
                continue
            current = _validate_one(aug, delta, manifest)
            if current.passed:
                passed.append(current)
                won = True
                break
        if not won:
            still_failed.append(current)
            _bounce_to_failed(staging_dir, nv.slug, current)

    return ValidationReport(passed=tuple(passed), failed=tuple(still_failed))
```

- [ ] **Step 4: Run to confirm pass**

Run: `pytest tests/test_batch_retry.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/rufino/engine/process/batch/retry.py tests/test_batch_retry.py
git commit -m "feat(batch): add retry loop with bouncing to failed/"
```

---

## Task 11: Collect pending Q&A and write to vault/questions/

**Files:**
- Create: `src/rufino/engine/process/batch/qa_pending.py`
- Test: `tests/test_batch_qa_pending.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_batch_qa_pending.py`:

```python
import json
from pathlib import Path

import pytest

from rufino.engine.process.batch.qa_pending import (
    PendingQA,
    collect_pending,
    write_questions_to_vault,
)


def _write_pending(staging: Path, slug: str, payload: dict) -> None:
    p = staging / "pending"
    p.mkdir(parents=True, exist_ok=True)
    (p / f"{slug}.json").write_text(json.dumps(payload))


def test_collect_pending_finds_all_across_workers(tmp_path):
    w1 = tmp_path / "workers" / "w001"
    w2 = tmp_path / "workers" / "w002"
    _write_pending(w1, "n1", {
        "origin": "process-batch", "run_id": "r1", "worker_id": "w001",
        "pending_note": "n1", "input_path": "inbox/g/n1.md",
        "trigger": "ambig", "context": "c", "question": "?",
    })
    _write_pending(w2, "n2", {
        "origin": "process-batch", "run_id": "r1", "worker_id": "w002",
        "pending_note": "n2", "input_path": "inbox/g/n2.md",
        "trigger": "ambig", "context": "c", "question": "?",
    })
    pendings = collect_pending(tmp_path)
    assert {p.pending_note for p in pendings} == {"n1", "n2"}


def test_collect_pending_skips_malformed(tmp_path):
    w1 = tmp_path / "workers" / "w001"
    (w1 / "pending").mkdir(parents=True)
    (w1 / "pending" / "broken.json").write_text("{not json")
    pendings = collect_pending(tmp_path)
    assert pendings == []


def test_write_questions_creates_question_files(tmp_path):
    vault = tmp_path / "vault"
    (vault / "questions").mkdir(parents=True)
    pendings = [PendingQA(
        origin="process-batch", run_id="r1", worker_id="w001",
        pending_note="n1", input_path="inbox/g/n1.md",
        trigger="ambig_materia", context="some ctx",
        question="What is the materia?",
    )]
    written = write_questions_to_vault(pendings, vault)
    assert len(written) == 1
    body = written[0].read_text()
    assert "What is the materia?" in body
    assert "answer:" in body
    assert "origin: process-batch" in body
    assert "pending_note: n1" in body
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/test_batch_qa_pending.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement qa_pending.py**

Create `src/rufino/engine/process/batch/qa_pending.py`:

```python
"""Collect pending Q&A blocks emitted by workers and write them to the vault.

Workers can decide a note triggers a qa_trigger from the adapter; in that case
they write `pending/<slug>.json` in their staging dir instead of the usual
augmented/+deltas/ pair. Rufino, after VALIDATE, scans for these and writes
a Q&A note into the vault's `questions/` directory.
"""
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PendingQA:
    origin: str
    run_id: str
    worker_id: str
    pending_note: str
    input_path: str
    trigger: str
    context: str
    question: str


def collect_pending(run_dir: Path) -> list[PendingQA]:
    out: list[PendingQA] = []
    workers_root = run_dir / "workers"
    if not workers_root.exists():
        return out
    for worker_dir in sorted(workers_root.iterdir()):
        pending_dir = worker_dir / "pending"
        if not pending_dir.is_dir():
            continue
        for p in sorted(pending_dir.glob("*.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            try:
                out.append(PendingQA(
                    origin=data["origin"], run_id=data["run_id"],
                    worker_id=data["worker_id"], pending_note=data["pending_note"],
                    input_path=data["input_path"], trigger=data["trigger"],
                    context=data.get("context", ""), question=data["question"],
                ))
            except KeyError:
                continue
    return out


def write_questions_to_vault(
    pendings: list[PendingQA], vault_root: Path,
) -> list[Path]:
    questions_dir = vault_root / "questions"
    questions_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for pending in pendings:
        qid = f"{pending.run_id}-{pending.worker_id}-{pending.pending_note}"
        path = questions_dir / f"{qid}.md"
        body = (
            "---\n"
            f"origin: {pending.origin}\n"
            f"run_id: {pending.run_id}\n"
            f"worker_id: {pending.worker_id}\n"
            f"pending_note: {pending.pending_note}\n"
            f"input_path: {pending.input_path}\n"
            f"trigger: {pending.trigger}\n"
            f"context: {pending.context!r}\n"
            "---\n\n"
            f"# {pending.question}\n\n"
            "answer: \n"
        )
        path.write_text(body, encoding="utf-8")
        written.append(path)
    return written
```

- [ ] **Step 4: Run to confirm pass**

Run: `pytest tests/test_batch_qa_pending.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/rufino/engine/process/batch/qa_pending.py tests/test_batch_qa_pending.py
git commit -m "feat(batch): collect worker pending Q&A and write to vault/questions/"
```

---

## Task 12: Implement consolidator

**Files:**
- Create: `src/rufino/engine/process/batch/consolidator.py`
- Test: `tests/test_batch_consolidator.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_batch_consolidator.py`:

```python
import json
from pathlib import Path

import pytest

from rufino.engine.process.batch.consolidator import (
    ConsolidationPlan,
    build_consolidator_system_prompt,
    validate_consolidation_plan,
)
from rufino.engine.process.batch.errors import ConsolidationError


def test_validate_plan_accepts_complete():
    raw = {
        "moves": [{"from": "workers/w/augmented/a.md", "to": "x/a.md"}],
        "concept_writes": [],
        "tag_index_updates": [],
        "log_entries": ["ok"],
    }
    parsed = validate_consolidation_plan(raw)
    assert isinstance(parsed, ConsolidationPlan)
    assert parsed.moves == [{"from": "workers/w/augmented/a.md", "to": "x/a.md"}]


def test_validate_plan_rejects_missing_key():
    with pytest.raises(ConsolidationError):
        validate_consolidation_plan({"moves": []})


def test_validate_plan_rejects_bad_move():
    raw = {"moves": [{"from": "x"}], "concept_writes": [],
           "tag_index_updates": [], "log_entries": []}
    with pytest.raises(ConsolidationError, match="move"):
        validate_consolidation_plan(raw)


def test_build_prompt_mentions_run_dir_and_slug():
    prompt = build_consolidator_system_prompt(
        run_dir=Path("/run"), vault_slug="myslug",
    )
    assert "/run" in prompt
    assert "myslug" in prompt
    assert "consolidation-plan.json" in prompt
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/test_batch_consolidator.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement consolidator.py**

Create `src/rufino/engine/process/batch/consolidator.py`:

```python
"""Run the consolidator: one `claude` invocation reads all workers' outputs
and emits `consolidation-plan.json` that Rufino then commits via the
transaction log.

If the consolidator times out or returns an empty plan, callers should
fall back to a naive commit (each augmented.md → destination, indices
appended per-delta, no cross-grupo concept dedup).
"""
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rufino.engine.process.batch.errors import ConsolidationError
from rufino.engine.process.batch.runner_helper import run_claude


_CONSOLIDATOR_PREAMBLE = """\
Sos el consolidator de Rufino corriendo después de un batch de workers.

Tu trabajo:

1. Leé TODOS los archivos en `{run_dir}/workers/*/augmented/*.md` y
   `{run_dir}/workers/*/deltas/*.json`.
2. Leé el estado actual del vault: `_meta/_tags.md`, `_meta/_index.md` y
   `conceptos/`.
3. Detectá conceptos duplicados emitidos independientemente por workers
   distintos.
4. Producí UN solo archivo: `{run_dir}/consolidation-plan.json` con este
   schema (todos los keys son listas; pueden estar vacías):

{{
  "moves": [{{"from": "<relative-to-run-dir>", "to": "<relative-to-vault>"}}, ...],
  "concept_writes": [{{"path": "conceptos/<slug>.md", "content": "...", "wins_over": [...]}}, ...],
  "tag_index_updates": [{{"tag": "<tag>", "notes": ["<slug>", ...]}}, ...],
  "log_entries": ["<line>", ...]
}}

Tools allowed: Read, Glob, Write, mcp__ask-rufino-{slug}__*. Usá Write SOLO para
el plan path.
"""


@dataclass(frozen=True)
class ConsolidationPlan:
    moves: list[dict[str, str]] = field(default_factory=list)
    concept_writes: list[dict[str, Any]] = field(default_factory=list)
    tag_index_updates: list[dict[str, Any]] = field(default_factory=list)
    log_entries: list[str] = field(default_factory=list)


def build_consolidator_system_prompt(*, run_dir: Path, vault_slug: str) -> str:
    return _CONSOLIDATOR_PREAMBLE.format(run_dir=run_dir, slug=vault_slug)


def validate_consolidation_plan(raw: dict) -> ConsolidationPlan:
    required_keys = {"moves", "concept_writes", "tag_index_updates", "log_entries"}
    missing = required_keys - set(raw.keys())
    if missing:
        raise ConsolidationError(f"consolidation plan missing keys: {sorted(missing)}")
    for k in required_keys:
        if not isinstance(raw[k], list):
            raise ConsolidationError(f"field {k!r} must be a list")
    for m in raw["moves"]:
        if not isinstance(m, dict) or "from" not in m or "to" not in m:
            raise ConsolidationError(f"bad move entry: {m!r}")
    return ConsolidationPlan(
        moves=list(raw["moves"]),
        concept_writes=list(raw["concept_writes"]),
        tag_index_updates=list(raw["tag_index_updates"]),
        log_entries=list(raw["log_entries"]),
    )


async def run_consolidator(
    *,
    run_dir: Path,
    vault_slug: str,
    timeout_seconds: float = 600.0,
) -> ConsolidationPlan | None:
    """Invoke the consolidator subprocess. Returns parsed plan on success or
    None on timeout / empty-output (caller falls back to naive commit).
    """
    prompt = build_consolidator_system_prompt(run_dir=run_dir, vault_slug=vault_slug)
    plan_path = run_dir / "consolidation-plan.json"
    argv = [
        "claude", "-p",
        "--system-prompt", prompt,
        "--allowedTools", f"Read,Glob,Write,mcp__ask-rufino-{vault_slug}__*",
        "--cwd", str(run_dir),
        "--",
        f"Escribí el plan a {plan_path}",
    ]
    env = os.environ.copy()
    result = await run_claude(
        argv=argv, cwd=run_dir, env=env, timeout_seconds=timeout_seconds,
    )
    if result.exit_code == 124:  # timeout
        return None
    if not plan_path.exists():
        return None
    try:
        raw = json.loads(plan_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ConsolidationError(f"consolidation plan invalid JSON: {e}") from e
    return validate_consolidation_plan(raw)
```

- [ ] **Step 4: Run to confirm pass**

Run: `pytest tests/test_batch_consolidator.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/rufino/engine/process/batch/consolidator.py tests/test_batch_consolidator.py
git commit -m "feat(batch): add consolidator + plan schema validation"
```

---

## Task 13: Implement committer (transaction-log apply)

**Files:**
- Create: `src/rufino/engine/process/batch/committer.py`
- Test: `tests/test_batch_committer.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_batch_committer.py`:

```python
import json
from pathlib import Path

import pytest

from rufino.engine.process.batch.committer import commit
from rufino.engine.process.batch.consolidator import ConsolidationPlan
from rufino.runtime.transaction_log import TransactionLog


def _setup_run(tmp_path: Path) -> tuple[Path, Path]:
    vault = tmp_path / "vault"
    run = vault / ".rufino" / "runs" / "r1"
    (run / "workers" / "w001" / "augmented").mkdir(parents=True)
    (run / "workers" / "w001" / "augmented" / "n1.md").write_text(
        "---\ntitle: n1\n---\n# body\n"
    )
    (vault / "_meta").mkdir(parents=True)
    (vault / "_meta" / "_tags.md").write_text("")
    return vault, run


def test_commit_moves_and_updates(tmp_path):
    vault, run = _setup_run(tmp_path)
    plan = ConsolidationPlan(
        moves=[{"from": "workers/w001/augmented/n1.md", "to": "apuntes/n1.md"}],
        concept_writes=[{"path": "conceptos/dfs.md", "content": "# DFS\n", "wins_over": []}],
        tag_index_updates=[{"tag": "materia/math", "notes": ["n1"]}],
        log_entries=["batch r1 ok"],
    )
    tx = TransactionLog(run / "commit.tx.json")
    commit(plan=plan, vault_root=vault, run_dir=run, tx_log=tx)

    assert (vault / "apuntes" / "n1.md").exists()
    assert (vault / "conceptos" / "dfs.md").read_text() == "# DFS\n"
    tags = (vault / "_meta" / "_tags.md").read_text()
    assert "materia/math" in tags
    assert "n1" in tags
    log = (vault / "_meta" / "_processing-log.md").read_text()
    assert "batch r1 ok" in log


def test_commit_rolls_back_on_escape(tmp_path):
    vault, run = _setup_run(tmp_path)
    bad = ConsolidationPlan(
        moves=[{"from": "workers/w001/augmented/n1.md", "to": "../../escape.md"}],
    )
    tx = TransactionLog(run / "commit.tx.json")
    with pytest.raises(Exception):
        commit(plan=bad, vault_root=vault, run_dir=run, tx_log=tx)

    assert (run / "workers" / "w001" / "augmented" / "n1.md").exists()
    assert not (tmp_path / "escape.md").exists()


def test_commit_empty_plan_is_noop(tmp_path):
    vault, run = _setup_run(tmp_path)
    tx = TransactionLog(run / "commit.tx.json")
    commit(plan=ConsolidationPlan(), vault_root=vault, run_dir=run, tx_log=tx)
    assert (run / "workers" / "w001" / "augmented" / "n1.md").exists()
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/test_batch_committer.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement committer.py**

Create `src/rufino/engine/process/batch/committer.py`:

```python
"""Apply a ConsolidationPlan to the vault via the transaction log."""
import shutil
from pathlib import Path

from rufino.engine.process.batch.consolidator import ConsolidationPlan
from rufino.engine.process.helpers.indices import (
    append_to_log,
    update_tag_index,
)
from rufino.runtime.transaction_log import (
    TransactionLog,
    apply_and_log,
    register_rollback,
)


def _safe_in_vault(vault_root: Path, rel: str) -> Path:
    target = (vault_root / rel).resolve()
    root = vault_root.resolve()
    if not target.is_relative_to(root):
        raise ValueError(f"path escapes vault: {rel!r}")
    return target


def _undo_move(target: str) -> None:
    if "\x00" not in target:
        return
    dest, src = target.split("\x00", 1)
    if Path(dest).exists():
        Path(src).parent.mkdir(parents=True, exist_ok=True)
        shutil.move(dest, src)


def _undo_concept_overwrite(target: str) -> None:
    if "\x00" not in target:
        return
    dest, backup = target.split("\x00", 1)
    if Path(backup).exists():
        shutil.copy2(backup, dest)
        Path(backup).unlink()


register_rollback("batch_undo_move", _undo_move)
register_rollback("batch_undo_concept_overwrite", _undo_concept_overwrite)


def commit(
    *,
    plan: ConsolidationPlan,
    vault_root: Path,
    run_dir: Path,
    tx_log: TransactionLog,
) -> None:
    """Apply plan via tx_log. On any failure, rollback restores state and the
    exception propagates."""
    try:
        for m in plan.moves:
            src = (run_dir / m["from"]).resolve()
            dest = _safe_in_vault(vault_root, m["to"])
            if not src.exists():
                raise FileNotFoundError(f"missing source: {src}")
            dest.parent.mkdir(parents=True, exist_ok=True)

            def _do_move(src=src, dest=dest):
                shutil.move(str(src), str(dest))

            apply_and_log(
                tx_log,
                op="batch_move",
                target=f"{dest}\x00{src}",
                apply_fn=_do_move,
                rollback="batch_undo_move",
            )

        for cw in plan.concept_writes:
            dest = _safe_in_vault(vault_root, cw["path"])
            dest.parent.mkdir(parents=True, exist_ok=True)
            existed = dest.exists()
            previous = dest.read_text(encoding="utf-8") if existed else None

            def _do_write(dest=dest, content=cw["content"]):
                dest.write_text(content, encoding="utf-8")

            if existed:
                backup = dest.with_suffix(dest.suffix + ".pre-batch")
                backup.write_text(previous, encoding="utf-8")
                apply_and_log(
                    tx_log,
                    op="batch_concept_write_overwrite",
                    target=f"{dest}\x00{backup}",
                    apply_fn=_do_write,
                    rollback="batch_undo_concept_overwrite",
                )
            else:
                apply_and_log(
                    tx_log,
                    op="batch_concept_write_new",
                    target=str(dest),
                    apply_fn=_do_write,
                    rollback="delete",
                )

        if plan.tag_index_updates:
            tag_index = vault_root / "_meta" / "_tags.md"
            snap = tag_index.with_suffix(tag_index.suffix + ".pre-batch")
            if tag_index.exists():
                shutil.copy2(tag_index, snap)
            else:
                snap.write_text("", encoding="utf-8")

            def _restore_tags(target=str(tag_index), backup=str(snap)):
                shutil.copy2(backup, target)

            register_rollback("batch_undo_tag_index", _restore_tags)
            for tu in plan.tag_index_updates:
                for note in tu["notes"]:
                    apply_and_log(
                        tx_log,
                        op="batch_tag_index_update",
                        target=f"{tag_index}\x00{snap}",
                        apply_fn=lambda tag=tu["tag"], note=note: update_tag_index(
                            tag_index, tag=tag, note_slug=note,
                        ),
                        rollback="batch_undo_tag_index",
                    )

        log_path = vault_root / "_meta" / "_processing-log.md"
        for entry in plan.log_entries:
            apply_and_log(
                tx_log,
                op="batch_log_append",
                target=str(log_path),
                apply_fn=lambda entry=entry: append_to_log(log_path, message=entry),
                rollback="rmdir_if_empty",
            )
    except Exception:
        tx_log.rollback()
        raise
```

- [ ] **Step 4: Run to confirm pass**

Run: `pytest tests/test_batch_committer.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/rufino/engine/process/batch/committer.py tests/test_batch_committer.py
git commit -m "feat(batch): add committer applying plan via transaction log"
```

---

## Task 14: Implement top-level runner

**Files:**
- Create: `src/rufino/engine/process/batch/runner.py`
- Test: `tests/test_batch_runner.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_batch_runner.py`:

```python
import asyncio
import os
from pathlib import Path

import pytest

from rufino.engine.process.batch.runner import (
    BatchRunResult,
    run_batch,
)


FAKE_DIR = Path("tests/fixtures/fake_claude").resolve()


@pytest.fixture(autouse=True)
def _fake_claude(monkeypatch):
    monkeypatch.setenv("PATH", str(FAKE_DIR) + os.pathsep + os.environ["PATH"])


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
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/test_batch_runner.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement runner.py**

Create `src/rufino/engine/process/batch/runner.py`:

```python
"""Top-level orchestration for `rufino process-batch`.

Six stages: STAGE → PLAN → DISPATCH → VALIDATE+RETRY → Q&A collect →
CONSOLIDATE (or naive fallback) → COMMIT.
"""
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from rufino.engine.process.batch.committer import commit
from rufino.engine.process.batch.consolidator import (
    ConsolidationPlan,
    run_consolidator,
)
from rufino.engine.process.batch.dispatcher import dispatch
from rufino.engine.process.batch.errors import (
    BatchError,
    WorkerSessionExpiredError,
)
from rufino.engine.process.batch.planner import build_plan
from rufino.engine.process.batch.qa_pending import (
    collect_pending,
    write_questions_to_vault,
)
from rufino.engine.process.batch.retry import retry_failed
from rufino.engine.process.batch.stager import stage_corpus
from rufino.engine.process.batch.validator import validate_worker_output
from rufino.engine.process.batch.worker_prompt import (
    build_worker_system_prompt,
)
from rufino.engine.process.manifest import parse_worker_manifest
from rufino.runtime.transaction_log import TransactionLog
from rufino.runtime.vault_slug import compute_vault_slug


@dataclass(frozen=True)
class BatchRunResult:
    run_id: str
    dry_run: bool
    notes_total: int = 0
    notes_ok: int = 0
    notes_failed: int = 0
    notes_pending_qa: int = 0
    plan_path: Path | None = None
    commit_skipped: bool = False


def _new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")


def _gather_concepts_top_n(vault_root: Path, n: int = 30) -> list[str]:
    conceptos = vault_root / "conceptos"
    if not conceptos.exists():
        return []
    return sorted([p.stem for p in conceptos.glob("*.md")])[:n]


def _ensure_gitignore(vault_root: Path) -> None:
    """Lazy migration: add `.rufino/runs/` to vault's .gitignore if present."""
    gi = vault_root / ".gitignore"
    if not gi.exists():
        return
    text = gi.read_text(encoding="utf-8")
    line = ".rufino/runs/"
    if line in text:
        return
    if not text.endswith("\n"):
        text += "\n"
    text += line + "\n"
    gi.write_text(text, encoding="utf-8")


def _naive_commit_plan(
    run_dir: Path, passed, destination_template: str,
) -> ConsolidationPlan:
    from rufino.engine.process.helpers.frontmatter import parse_frontmatter
    moves = []
    tag_map: dict[str, list[str]] = {}
    for nv in passed:
        slug = nv.slug
        try:
            fm, _ = parse_frontmatter(nv.augmented_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        variables = {k: v for k, v in fm.items() if isinstance(v, str)}
        variables.setdefault("slug", slug)
        try:
            dest_rel = destination_template.format(**variables)
        except KeyError:
            continue
        rel_from = nv.augmented_path.relative_to(run_dir)
        moves.append({"from": str(rel_from), "to": dest_rel})
        for tag in fm.get("tags", []):
            tag_map.setdefault(tag, []).append(slug)
    return ConsolidationPlan(
        moves=moves, concept_writes=[],
        tag_index_updates=[{"tag": t, "notes": ns} for t, ns in tag_map.items()],
        log_entries=[f"batch-naive-commit notes={len(moves)}"],
    )


async def run_batch(
    *,
    source: Path,
    adapter_dir: Path,
    vault_root: Path,
    workers: int | None,
    batch_size: int | None,
    dry_run: bool,
    skip_consolidator: bool = False,
    timeout_seconds: float = 300.0,
) -> BatchRunResult:
    vault_root = vault_root.expanduser().resolve()
    adapter_dir = adapter_dir.expanduser().resolve()
    source = source.expanduser().resolve()

    if not adapter_dir.is_dir():
        raise BatchError(f"adapter_dir {adapter_dir} is not a directory")
    manifest_path = adapter_dir / "manifest.yaml"
    prompt_path = adapter_dir / "prompt.md"
    if not manifest_path.exists():
        raise BatchError(f"adapter missing manifest.yaml: {adapter_dir}")
    manifest = parse_worker_manifest(manifest_path.read_text(encoding="utf-8"))
    adapter_prompt = prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else ""

    run_id = _new_run_id()
    run_dir = vault_root / ".rufino" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    _ensure_gitignore(vault_root)

    # STAGE
    staged = stage_corpus(source, run_dir)
    if not staged.groups:
        raise BatchError("corpus is empty after staging — nothing to process")

    # PLAN
    effective_batch_size = batch_size if batch_size is not None else manifest.batch_size
    plan = build_plan(
        staged, run_id=run_id, adapter_dir=str(adapter_dir),
        batch_size=effective_batch_size,
    )
    plan_path = run_dir / "plan.json"
    plan_path.write_text(plan.to_json(), encoding="utf-8")
    if dry_run:
        return BatchRunResult(
            run_id=run_id, dry_run=True,
            notes_total=sum(len(w.notes) for w in plan.workers),
            plan_path=plan_path, commit_skipped=True,
        )

    # DISPATCH
    vault_slug = compute_vault_slug(vault_root)
    concepts_top = _gather_concepts_top_n(vault_root)
    effective_workers = workers if workers is not None else min(4, max(1, len(plan.workers)))

    def _prompt_for(assignment):
        staging_dir = run_dir / "workers" / assignment.worker_id
        return build_worker_system_prompt(
            manifest=manifest, adapter_prompt_text=adapter_prompt,
            assignment=assignment, vault_slug=vault_slug,
            staging_dir=staging_dir, vault_concepts_top_n=concepts_top,
            run_id=run_id,
        )

    await dispatch(
        plan=plan, run_dir=run_dir,
        system_prompt_for=_prompt_for, vault_slug=vault_slug,
        max_workers=effective_workers, timeout_seconds=timeout_seconds,
    )

    # VALIDATE + RETRY
    all_passed = []
    all_failed = []
    for assignment in plan.workers:
        staging_dir = run_dir / "workers" / assignment.worker_id
        report = validate_worker_output(staging_dir, manifest)
        if report.failed:
            retry_report = await retry_failed(
                failed=report.failed, manifest=manifest,
                adapter_prompt_text=adapter_prompt,
                worker_assignment=assignment, run_dir=run_dir,
                vault_slug=vault_slug, max_retries=2,
                timeout_seconds=timeout_seconds,
            )
            all_passed.extend(report.passed)
            all_passed.extend(retry_report.passed)
            all_failed.extend(retry_report.failed)
        else:
            all_passed.extend(report.passed)

    # Q&A collection
    pendings = collect_pending(run_dir)
    if pendings:
        write_questions_to_vault(pendings, vault_root)

    # CONSOLIDATE (or naive fallback)
    if skip_consolidator:
        plan_obj = _naive_commit_plan(
            run_dir, tuple(all_passed), manifest.destination_path,
        )
    else:
        try:
            plan_obj = await run_consolidator(
                run_dir=run_dir, vault_slug=vault_slug, timeout_seconds=600.0,
            )
        except Exception:
            plan_obj = None
        if plan_obj is None:
            plan_obj = _naive_commit_plan(
                run_dir, tuple(all_passed), manifest.destination_path,
            )

    # COMMIT
    tx = TransactionLog(run_dir / "commit.tx.json")
    commit(plan=plan_obj, vault_root=vault_root, run_dir=run_dir, tx_log=tx)

    summary = {
        "run_id": run_id,
        "notes_total": sum(len(w.notes) for w in plan.workers),
        "notes_ok": len(all_passed),
        "notes_failed": len(all_failed),
        "notes_pending_qa": len(pendings),
    }
    (run_dir / "run.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    return BatchRunResult(
        run_id=run_id, dry_run=False,
        notes_total=summary["notes_total"], notes_ok=summary["notes_ok"],
        notes_failed=summary["notes_failed"],
        notes_pending_qa=summary["notes_pending_qa"],
        plan_path=plan_path,
    )
```

- [ ] **Step 4: Run to confirm pass**

Run: `pytest tests/test_batch_runner.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/rufino/engine/process/batch/runner.py tests/test_batch_runner.py
git commit -m "feat(batch): add top-level runner orchestrating all six stages"
```

---

## Task 15: Wire `rufino process-batch` CLI command

**Files:**
- Modify: `src/rufino/cli.py`
- Test: `tests/test_cli_process_batch.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli_process_batch.py`:

```python
import os
from pathlib import Path

from click.testing import CliRunner

from rufino.cli import cli


FAKE_DIR = Path("tests/fixtures/fake_claude").resolve()


def _make_adapter(tmp: Path) -> Path:
    adapter = tmp / "adapter"
    adapter.mkdir()
    (adapter / "manifest.yaml").write_text("""
adapter_name: x
note_type: x
applies_when: {source_dir: inbox/, matches_pattern: ["*.md"]}
llm: sonnet
mode_default: full
output_schema: {required: {title: string, materia: string}}
triple_vocabulary: [tema-de]
tag_axes: [{axis: materia, format: "materia/{slug}"}]
destination_path: "apuntes/{slug}.md"
""")
    (adapter / "prompt.md").write_text("# adapter prompt\n")
    return adapter


def test_process_batch_dry_run(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(FAKE_DIR) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "augment")
    adapter = _make_adapter(tmp_path)
    source = tmp_path / "corpus"
    (source / "math").mkdir(parents=True)
    (source / "math" / "n1.md").write_text("# n\n")
    vault = tmp_path / "vault"

    runner = CliRunner()
    result = runner.invoke(cli, [
        "process-batch", str(source),
        "--adapter", str(adapter),
        "--vault", str(vault),
        "--dry-run",
    ])
    assert result.exit_code == 0, result.output
    assert "plan" in result.output.lower()
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/test_cli_process_batch.py -v`
Expected: FAIL — no such command.

- [ ] **Step 3: Append the command to cli.py**

Append at the end of `src/rufino/cli.py`:

```python
@cli.command(name="process-batch")
@click.argument("source", type=click.Path(exists=True, path_type=Path))
@click.option("--adapter", "adapter_dir", required=True,
              type=click.Path(exists=True, file_okay=False, path_type=Path),
              help="Path to the Process adapter directory")
@click.option("--vault", "vault_root", required=True,
              type=click.Path(path_type=Path),
              help="Vault root")
@click.option("--workers", type=int, default=None,
              help="Max concurrent workers (default: min(4, num_groups))")
@click.option("--batch-size", "batch_size", type=int, default=None,
              help="Override the adapter manifest's batch_size")
@click.option("--dry-run", is_flag=True,
              help="Stop after PLAN; print the plan path; do not spawn workers")
def process_batch_cmd(
    source: Path, adapter_dir: Path, vault_root: Path,
    workers: int | None, batch_size: int | None, dry_run: bool,
) -> None:
    """Process a corpus (ZIP or directory) into augmented vault notes."""
    import asyncio
    from rufino.engine.process.batch.errors import (
        BatchError, WorkerSessionExpiredError,
    )
    from rufino.engine.process.batch.runner import run_batch

    try:
        result = asyncio.run(run_batch(
            source=source, adapter_dir=adapter_dir, vault_root=vault_root,
            workers=workers, batch_size=batch_size, dry_run=dry_run,
        ))
    except WorkerSessionExpiredError as e:
        click.echo(f"Error: {e}", err=True)
        raise click.exceptions.Exit(code=1)
    except BatchError as e:
        click.echo(f"Error: {e}", err=True)
        raise click.exceptions.Exit(code=1)
    except FileNotFoundError as e:
        if "claude" in str(e):
            click.echo("Error: `claude` no encontrado en PATH.", err=True)
            raise click.exceptions.Exit(code=127)
        raise

    if result.dry_run:
        click.echo(f"dry-run: plan written to {result.plan_path}")
        click.echo(f"notes_total={result.notes_total}")
        return
    click.echo(
        f"run_id={result.run_id} total={result.notes_total} "
        f"ok={result.notes_ok} failed={result.notes_failed} "
        f"pending_qa={result.notes_pending_qa}"
    )
```

- [ ] **Step 4: Run to confirm pass**

Run: `pytest tests/test_cli_process_batch.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/rufino/cli.py tests/test_cli_process_batch.py
git commit -m "feat(cli): add rufino process-batch command"
```

---

## Task 16: Wire qa-poll resumption for process-batch origins

**Files:**
- Modify: `src/rufino/cli.py` (replace stubbed handler)
- Create: `src/rufino/engine/process/batch/qa_resume.py`
- Test: `tests/test_cli_qa_poll_resumption.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli_qa_poll_resumption.py`:

```python
import json
import os
from pathlib import Path

from click.testing import CliRunner

from rufino.cli import cli


FAKE_DIR = Path("tests/fixtures/fake_claude").resolve()


def _setup_pending_question(vault: Path, run_id: str = "r1") -> Path:
    qd = vault / "questions"
    qd.mkdir(parents=True)
    qf = qd / f"{run_id}-w001-n1.md"
    qf.write_text(
        "---\n"
        "origin: process-batch\n"
        f"run_id: {run_id}\n"
        "worker_id: w001\n"
        "pending_note: n1\n"
        "input_path: inbox/g/n1.md\n"
        "trigger: ambig\n"
        "context: c\n"
        "---\n\n"
        "# What is the materia?\n\n"
        "answer: math 101\n"
    )
    return qf


def _setup_run_dir(vault: Path, run_id: str = "r1") -> Path:
    rd = vault / ".rufino" / "runs" / run_id
    (rd / "inbox" / "g").mkdir(parents=True)
    (rd / "inbox" / "g" / "n1.md").write_text("# n\n")
    (rd / "workers" / "w001" / "pending").mkdir(parents=True)
    (rd / "plan.json").write_text(json.dumps({
        "run_id": run_id,
        "adapter_dir": str(rd.parent.parent.parent / "_adapter"),
        "workers": [],
    }))
    return rd


def _setup_adapter(vault: Path) -> Path:
    a = vault / ".rufino" / "runs" / "_adapter"
    a.mkdir(parents=True)
    (a / "manifest.yaml").write_text("""
adapter_name: x
note_type: x
applies_when: {source_dir: inbox/, matches_pattern: ["*.md"]}
llm: sonnet
mode_default: full
output_schema: {required: {title: string, materia: string}}
triple_vocabulary: [tema-de]
tag_axes: [{axis: materia, format: "materia/{slug}"}]
destination_path: "apuntes/{slug}.md"
""")
    (a / "prompt.md").write_text("# p\n")
    return a


def test_qa_poll_archives_answered_question(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(FAKE_DIR) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "augment")

    vault = tmp_path / "vault"
    state = tmp_path / "state"
    (vault / "_meta").mkdir(parents=True)
    (vault / "_meta" / "_tags.md").write_text("")
    state.mkdir()

    _setup_adapter(vault)
    _setup_run_dir(vault)
    qf = _setup_pending_question(vault)
    # Make the plan point to the real adapter dir:
    plan_path = vault / ".rufino" / "runs" / "r1" / "plan.json"
    data = json.loads(plan_path.read_text())
    data["adapter_dir"] = str(vault / ".rufino" / "runs" / "_adapter")
    plan_path.write_text(json.dumps(data))

    runner = CliRunner()
    result = runner.invoke(cli, [
        "qa-poll", "--vault", str(vault), "--state-dir", str(state),
    ])
    assert result.exit_code == 0, result.output
    assert not qf.exists()
    archived = vault / "questions" / "answered" / qf.name
    assert archived.exists()
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/test_cli_qa_poll_resumption.py -v`
Expected: FAIL — current `qa_poll_cmd` exits 2 on any answered question.

- [ ] **Step 3: Implement qa_resume.py**

Create `src/rufino/engine/process/batch/qa_resume.py`:

```python
"""Resume a process-batch Q&A: re-invoke a single-note worker with the
user's answer injected, then archive the question on success.
"""
import json
import os
import shutil
from pathlib import Path

import yaml

from rufino.engine.process.batch.dispatcher import (
    SESSION_EXPIRED_EXIT_CODE,
    build_argv,
)
from rufino.engine.process.batch.errors import WorkerSessionExpiredError
from rufino.engine.process.batch.planner import WorkerAssignment
from rufino.engine.process.batch.runner_helper import run_claude
from rufino.engine.process.batch.validator import _validate_one
from rufino.engine.process.batch.worker_prompt import (
    build_worker_system_prompt,
)
from rufino.engine.process.manifest import parse_worker_manifest


def _read_question(qfile: Path) -> dict:
    text = qfile.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    _, fm_text, body = text.split("---", 2)
    fm = yaml.safe_load(fm_text) or {}
    answer = ""
    for line in body.splitlines():
        if line.strip().startswith("answer:"):
            answer = line.split(":", 1)[1].strip()
            break
    fm["answer"] = answer
    return fm


_RESUME_APPENDIX = """

ANSWERED

El usuario respondió la pregunta de Q&A. Información:

  - trigger: {trigger}
  - contexto guardado: {context}
  - respuesta del usuario: {answer}

Rehacé esta nota con la respuesta integrada. Output normal: augmented/<slug>.md
y deltas/<slug>.json.
"""


async def resume_pending_qa(
    *, vault_root: Path, question_file: Path,
) -> bool:
    meta = _read_question(question_file)
    if not meta.get("answer"):
        return False
    if meta.get("origin") != "process-batch":
        return False
    run_id = meta["run_id"]
    worker_id = meta["worker_id"]
    slug = meta["pending_note"]
    run_dir = vault_root / ".rufino" / "runs" / run_id
    if not run_dir.exists():
        return False

    plan_data = json.loads((run_dir / "plan.json").read_text(encoding="utf-8"))
    adapter_dir = Path(plan_data["adapter_dir"])
    manifest = parse_worker_manifest(
        (adapter_dir / "manifest.yaml").read_text(encoding="utf-8")
    )
    adapter_prompt = (
        (adapter_dir / "prompt.md").read_text(encoding="utf-8")
        if (adapter_dir / "prompt.md").exists() else ""
    )

    inbox = run_dir / "inbox"
    matches = list(inbox.rglob(f"{slug}.md")) + list(inbox.rglob(f"{slug}.pdf"))
    if not matches:
        return False
    note_path = matches[0]

    staging_dir = run_dir / "workers" / worker_id
    staging_dir.mkdir(parents=True, exist_ok=True)
    assignment = WorkerAssignment(
        worker_id=worker_id, group=note_path.parent.name, notes=(note_path,),
    )

    base_prompt = build_worker_system_prompt(
        manifest=manifest, adapter_prompt_text=adapter_prompt,
        assignment=assignment, vault_slug="",
        staging_dir=staging_dir, vault_concepts_top_n=[],
        run_id=run_id,
    )
    appendix = _RESUME_APPENDIX.format(
        trigger=meta.get("trigger", ""),
        context=meta.get("context", ""),
        answer=meta["answer"],
    )

    env = os.environ.copy()
    env["FAKE_CLAUDE_NOTES"] = str(note_path)
    argv = build_argv(
        system_prompt=base_prompt + appendix,
        staging_dir=staging_dir, vault_slug="",
    )
    result = await run_claude(
        argv=argv, cwd=staging_dir, env=env, timeout_seconds=300.0,
    )
    if result.exit_code == SESSION_EXPIRED_EXIT_CODE:
        raise WorkerSessionExpiredError(
            "Tu sesión Claude está expirada. Corré `claude login`."
        )

    pending = staging_dir / "pending" / f"{slug}.json"
    if pending.exists():
        pending.unlink()

    aug = staging_dir / "augmented" / f"{slug}.md"
    delta = staging_dir / "deltas" / f"{slug}.json"
    if not aug.exists():
        return False
    validation = _validate_one(aug, delta, manifest)
    if not validation.passed:
        return False

    archived = vault_root / "questions" / "answered"
    archived.mkdir(parents=True, exist_ok=True)
    shutil.move(str(question_file), archived / question_file.name)
    return True
```

- [ ] **Step 4: Replace `qa_poll_cmd` in cli.py**

In `src/rufino/cli.py`, locate the existing `qa_poll_cmd` and replace it (and the `_ResumptionNotImplemented` class above it, if present) with:

```python
@cli.command(name="qa-poll")
@click.option("--vault", "vault_root", required=True, type=click.Path(path_type=Path))
@click.option("--state-dir", "state_dir", required=True, type=click.Path(path_type=Path))
def qa_poll_cmd(vault_root: Path, state_dir: Path) -> None:
    """Poll questions/ for answered questions and resume their workers."""
    import asyncio
    from rufino.engine.process.batch.errors import WorkerSessionExpiredError
    from rufino.engine.process.batch.qa_resume import resume_pending_qa

    questions_dir = vault_root / "questions"
    if not questions_dir.exists():
        click.echo("dispatched=0")
        return

    answered: list[Path] = []
    for qf in sorted(questions_dir.glob("*.md")):
        text = qf.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("answer:") and stripped not in ("answer:", "answer: "):
                answered.append(qf)
                break

    dispatched = 0
    failures: list[str] = []

    async def _process_all():
        nonlocal dispatched
        for qf in answered:
            try:
                ok = await resume_pending_qa(vault_root=vault_root, question_file=qf)
            except WorkerSessionExpiredError as e:
                failures.append(str(e))
                continue
            if ok:
                dispatched += 1

    asyncio.run(_process_all())
    click.echo(f"dispatched={dispatched}")
    if failures:
        for f in failures:
            click.echo(f"Error: {f}", err=True)
        raise click.exceptions.Exit(code=1)
```

- [ ] **Step 5: Run to confirm pass**

Run: `pytest tests/test_cli_qa_poll_resumption.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/rufino/cli.py src/rufino/engine/process/batch/qa_resume.py tests/test_cli_qa_poll_resumption.py
git commit -m "feat(qa): wire qa-poll resumption for process-batch origins"
```

---

## Task 17: Version bump + migration script

**Files:**
- Modify: `src/rufino/version.py`
- Modify: `pyproject.toml`
- Create: `migrations/0.0.3-to-0.1.0.sh`

- [ ] **Step 1: Bump VERSION**

Edit `src/rufino/version.py`:

```python
VERSION = "0.1.0"
```

- [ ] **Step 2: Bump pyproject.toml**

In `pyproject.toml`, change `version = "0.0.3"` to `version = "0.1.0"`.

- [ ] **Step 3: Create migration script**

Create `migrations/0.0.3-to-0.1.0.sh` (`chmod +x`):

```bash
#!/usr/bin/env bash
# Migration 0.0.3 → 0.1.0
#
# v0.1.0 adds `rufino process-batch` and one optional field (`batch_size`)
# to the adapter manifest schema. Vault-side adjustment (adding
# `.rufino/runs/` to the vault's .gitignore) happens lazily at the first
# process-batch run per vault, so this migration does NOT enumerate vaults.
set -euo pipefail

echo "0.0.3 → 0.1.0: no state changes required."
```

- [ ] **Step 4: Run the full test suite**

Run: `pytest -x -q`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/rufino/version.py pyproject.toml migrations/0.0.3-to-0.1.0.sh
git commit -m "chore: bump version 0.0.3 → 0.1.0 + migration marker"
```

---

## Task 18: End-to-end integration test

**Files:**
- Create: `tests/integration/__init__.py` (if missing)
- Create: `tests/integration/test_batch_end_to_end.py`

- [ ] **Step 1: Write the test**

Create `tests/integration/__init__.py` (empty) if missing.

Create `tests/integration/test_batch_end_to_end.py`:

```python
"""End-to-end test for `rufino process-batch` using the fake claude fixture."""
import asyncio
import json
import os
from pathlib import Path

import pytest

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
```

- [ ] **Step 2: Run to confirm pass**

Run: `pytest tests/integration/test_batch_end_to_end.py -v`
Expected: PASS.

- [ ] **Step 3: Run the full suite to catch regressions**

Run: `pytest -q`
Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/__init__.py tests/integration/test_batch_end_to_end.py
git commit -m "test(batch): end-to-end integration covering mixed formats"
```

---

## Task 19: Update docs

**Files:**
- Modify: `docs/primitives/process.md`
- Modify: `docs/adapters/worker-adapter.md`
- Modify: `README.md`
- Modify: `CLAUDE.md` (project file)

- [ ] **Step 1: Add "Batch processing" section to `docs/primitives/process.md`**

Edit `docs/primitives/process.md`. After the "Modos" table, insert:

```markdown
## Batch processing (v0.1.0+)

Para procesar un corpus entero (ZIP de Google Docs, carpeta con muchos
PDFs/docx/md, etc.):

```bash
rufino process-batch <zip-or-dir> \
  --adapter <process-adapter-dir> \
  --vault <vault-root> \
  [--workers N] [--batch-size N] [--dry-run]
```

Rufino NO embebe un LLM client — orquesta `claude` headless como workers en
paralelo. Flujo en seis etapas:

1. **STAGE** — descomprime ZIP (fix encoding cp437), convierte `.docx`/`.pptx`
   a markdown, deja `.md`/`.txt`/`.pdf` verbatim.
2. **PLAN** — agrupa por carpeta (1 grupo = 1 materia), parte grupos
   > `batch_size` en sub-batches, emite `plan.json`. `--dry-run` corta acá.
3. **DISPATCH** — invoca `claude` headless en paralelo bajo un asyncio
   semaphore. Cada worker en su staging dir.
4. **VALIDATE + RETRY** — validador post-hoc. Fallos disparan retry con prompt
   aumentado; tras max 2 retries, la nota cae a `failed/<slug>/`.
5. **CONSOLIDATE** — un Claude consolidador lee todos los outputs y produce
   `consolidation-plan.json`. Timeout / plan vacío → fallback a naive commit.
6. **COMMIT** — Rufino aplica el plan al vault vía el transaction log.

Detalles en `docs/superpowers/specs/2026-05-18-process-batch-via-claude-orchestration-design.md`.

### Q&A durante batch

Si un worker dispara un `qa_trigger`, escribe `pending/<slug>.json` en su
staging dir. Rufino, post-validate, escribe una pregunta a
`<vault>/questions/<id>.md` (con `origin: process-batch`). El COMMIT para
esa nota se difiere hasta que el usuario responde y corre `rufino qa-poll`,
que retoma con la respuesta inyectada al prompt y archiva la pregunta a
`questions/answered/`.
```

Replace the "Estado v0.0.2" section with:

```markdown
## Estado v0.1.0

- ✅ `mode_default: light` — operativo (registro + file move sin LLM)
- ✅ `mode_default: lint` — operativo (validación pure)
- ✅ Batch processing vía `rufino process-batch` — orquesta `claude` headless
- ⏸ Single-note `rufino process --mode full` — sigue stubbed (exits 2); usá
  `process-batch` apuntando a una carpeta de 1 archivo para single-note
- ✅ Q&A loop end-to-end (worker emite pending, Rufino escribe pregunta,
  `qa-poll` resume y archiva)
- ⏸ `transform_hook` — manifest parsea, runner no invoca
```

- [ ] **Step 2: Document `batch_size` in `docs/adapters/worker-adapter.md`**

In `docs/adapters/worker-adapter.md`, find the manifest schema block and add after `transform_hook`:

```yaml
batch_size: <int>                    # optional, default 10 — workers process
                                      # up to this many notes per spawn during
                                      # rufino process-batch
```

- [ ] **Step 3: Update README.md**

In `README.md`, in the commands list, add:

```markdown
- `rufino process-batch <zip-or-dir>` — batch-process a corpus into augmented vault notes (v0.1.0)
```

- [ ] **Step 4: Update project CLAUDE.md**

Edit `/Users/val/Files/codeProjects/rufino-framework/CLAUDE.md`. In the "Currently deferred" section, update to:

```markdown
## Currently deferred (don't be surprised)

- `transform_hook` / `transform.py` — manifest accepts the field, runner does not yet invoke it.
- Ingest `output_mode: emit_augmented` — manifest parses, dispatcher not wired.
- `rufino process --mode full` (single-note) — exits with code 2. For batch processing, use `rufino process-batch`. Reviving the single-note path is out of scope for v0.1.0.
- `_NoopEmbeddings` in `cli.py` — placeholder embedder until the real Ollama wiring lands.
```

- [ ] **Step 5: Commit docs**

```bash
git add docs/primitives/process.md docs/adapters/worker-adapter.md README.md CLAUDE.md
git commit -m "docs: cover rufino process-batch and v0.1.0 status"
```

---

## Final verification

- [ ] **Step 1: Full test suite**

Run: `pytest -q`
Expected: all tests pass.

- [ ] **Step 2: Coverage on batch modules**

Run: `pytest --cov=src/rufino/engine/process/batch --cov-report=term-missing tests/test_batch_* tests/integration/test_batch_end_to_end.py`
Expected: ≥ 85% on `engine/process/batch/`.

- [ ] **Step 3: Manual smoke (CLI)**

Build a tiny corpus and an adapter:

```bash
mkdir -p /tmp/smoke/math && echo "# Triangulation" > /tmp/smoke/math/n1.md
mkdir -p /tmp/smoke-adapter
cat > /tmp/smoke-adapter/manifest.yaml <<'EOF'
adapter_name: smoke
note_type: smoke
applies_when: {source_dir: inbox/, matches_pattern: ["*.md"]}
llm: sonnet
mode_default: full
output_schema: {required: {title: string, materia: string}}
triple_vocabulary: [tema-de]
tag_axes: [{axis: materia, format: "materia/{slug}"}]
destination_path: "apuntes/{slug}.md"
EOF
echo "# adapter prompt" > /tmp/smoke-adapter/prompt.md
rufino process-batch /tmp/smoke --adapter /tmp/smoke-adapter --vault /tmp/smoke-vault --dry-run
```

Expected: `dry-run: plan written to /tmp/smoke-vault/.rufino/runs/<run-id>/plan.json`.

---

## Self-review checklist

1. **Spec coverage** — every section of the spec maps to at least one task:
   - §2.1 STAGE → Task 4
   - §2.2 PLAN → Task 5
   - §2.3 DISPATCH → Task 8
   - §2.4 Worker prompt → Task 6
   - §2.5 I/O contract → enforced by Task 6 (prompt) + Task 9 (validator)
   - §2.6 VALIDATE + RETRY → Tasks 9, 10
   - §2.7 Q&A blocks → Task 11
   - §2.8 CONSOLIDATE → Task 12 + Task 14 (naive fallback)
   - §2.9 COMMIT → Task 13 + Task 14
   - §3 batch_size field → Task 1
   - §4 module layout → Tasks 2–14
   - §5 isolation → staging dir per worker (Task 8) + commit only via committer (Task 13)
   - §6 auth → user's `claude` session, nothing to wire
   - §7 error handling → Task 8 (session expired), Task 10 (retry+bouncing), Task 12 (consolidator timeout), Task 13 (commit rollback)
   - §8 testing → every task has tests; integration in Task 18
   - §9 Q&A resumption → Task 16
   - §10 versioning + lazy gitignore → Task 17 + runner `_ensure_gitignore` (Task 14)

2. **No placeholders** — no `TBD`, `TODO`, `implement later`, `add error handling`, `similar to Task N`. All code is concrete.

3. **Type consistency** — `WorkerAssignment`, `Plan`, `StagedCorpus`, `ValidationReport`, `NoteValidation`, `ConsolidationPlan`, `BatchRunResult` defined in first task and used unchanged after. `run_claude` returns `ClaudeResult` everywhere. `build_argv` exported from `dispatcher.py` and reused in `retry.py` and `qa_resume.py`. `apply_and_log` reused from `runtime/transaction_log.py` with kwargs `op`/`target`/`apply_fn`/`rollback`.
