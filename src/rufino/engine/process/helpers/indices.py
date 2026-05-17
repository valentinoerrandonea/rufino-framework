from datetime import datetime, timezone
from pathlib import Path


def update_tag_index(tag_index: Path, *, tag: str, note_slug: str) -> None:
    """Append a (tag, note) line to the tag index. Idempotent for (tag,note) pairs."""
    line = f"- `{tag}` → [[{note_slug}]]\n"
    existing = tag_index.read_text() if tag_index.exists() else "# Tags\n"
    if line in existing:
        return
    tag_index.write_text(existing + line)


def append_to_log(log: Path, *, message: str) -> None:
    """Append a timestamped line to the processing log."""
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "")
    existing = log.read_text() if log.exists() else "# Processing log\n"
    log.write_text(existing + f"- {ts}Z — {message}\n")
