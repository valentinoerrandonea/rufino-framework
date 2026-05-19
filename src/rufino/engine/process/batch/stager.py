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


def _extract_zip(zip_path: Path, dest: Path, skipped: list[Path]) -> None:
    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as e:
        raise StagingError(f"corrupt zip {zip_path}: {e}") from e
    dest_resolved = dest.resolve()
    with zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            corrected = _fix_zip_name(info.filename)
            target = (dest / corrected).resolve()
            if not target.is_relative_to(dest_resolved):
                log.warning("skipping zip entry with unsafe path: %r", info.filename)
                skipped.append(Path(info.filename))
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)


def _stage_one_file(
    src_file: Path,
    inbox_group_dir: Path,
    rel_under_group: Path,
    skipped: list[Path],
) -> Path | None:
    suffix = src_file.suffix.lower()
    target_dir = inbox_group_dir / rel_under_group.parent
    if suffix in PASSTHROUGH_EXTS:
        target = target_dir / src_file.name
        if target.exists():
            raise StagingError(f"staging collision at {target}")
        target_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_file, target)
        return target
    if suffix in CONVERTIBLE_EXTS:
        target = target_dir / (src_file.stem + ".md")
        if target.exists():
            raise StagingError(f"staging collision at {target}")
        try:
            md = convert_to_markdown(src_file)
        except (ConversionError, UnsupportedFormatError) as e:
            log.warning("skipping %s: %s", src_file, e)
            skipped.append(src_file)
            return None
        target_dir.mkdir(parents=True, exist_ok=True)
        target.write_text(md, encoding="utf-8")
        return target
    log.warning("skipping unsupported format %s", src_file)
    skipped.append(src_file)
    return None


def stage_corpus(source: Path, run_dir: Path) -> StagedCorpus:
    """Stage a corpus (ZIP or directory) under <run_dir>/inbox/<group>/.

    Returns a StagedCorpus mapping group → list of staged Paths inside run_dir.
    """
    staged = StagedCorpus()
    corpus_root: Path
    if source.is_file() and source.suffix.lower() == ".zip":
        extracted_temp = run_dir / "_extracted"
        extracted_temp.mkdir(parents=True, exist_ok=True)
        _extract_zip(source, extracted_temp, staged.skipped)
        corpus_root = extracted_temp
    elif source.is_dir():
        corpus_root = source
    else:
        raise StagingError(f"source {source!r} must be a directory or .zip file")

    inbox_root = run_dir / "inbox"
    inbox_root.mkdir(parents=True, exist_ok=True)

    for file in sorted(corpus_root.rglob("*")):
        if not file.is_file():
            continue
        rel = file.relative_to(corpus_root)
        if len(rel.parts) > 1:
            group = rel.parts[0]
            rel_under_group = Path(*rel.parts[1:])
        else:
            group = "_root"
            rel_under_group = rel
        inbox_group = inbox_root / group
        target = _stage_one_file(file, inbox_group, rel_under_group, staged.skipped)
        if target is not None:
            staged.groups.setdefault(group, []).append(target)
    return staged
