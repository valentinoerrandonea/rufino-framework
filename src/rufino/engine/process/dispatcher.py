from dataclasses import dataclass
from pathlib import Path
from rufino.engine.process.helpers.frontmatter import parse_frontmatter
from rufino.engine.process.helpers.indices import update_tag_index, append_to_log


@dataclass
class ProcessResult:
    success: bool
    note_path: Path
    message: str = ""


def process_note(
    *,
    note_path: Path,
    vault_root: Path,
    mode: str,
) -> ProcessResult:
    """Process a note. Modes: light (indices only), full (LLM augment), lint (validate)."""
    if mode == "light":
        return _process_light(note_path=note_path, vault_root=vault_root)
    raise NotImplementedError(f"Mode {mode!r} not implemented yet (Task 8 covers full)")


def _process_light(*, note_path: Path, vault_root: Path) -> ProcessResult:
    text = note_path.read_text()
    fm, _body = parse_frontmatter(text)
    tags = fm.get("tags", [])

    tag_index = vault_root / "_meta" / "_tags.md"
    note_slug = note_path.stem
    for tag in tags:
        update_tag_index(tag_index, tag=tag, note_slug=note_slug)

    log = vault_root / "_meta" / "_processing-log.md"
    append_to_log(log, message=f"light-processed {note_slug}")

    return ProcessResult(success=True, note_path=note_path, message="light OK")
