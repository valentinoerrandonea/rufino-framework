"""Shared filtering helpers for query backends and MCP tools."""
from pathlib import Path
from typing import Iterator


EXCLUDED_DIRS = frozenset({"_meta", ".obsidian", ".git", ".trash", "node_modules"})


def iter_user_notes(vault_root: Path) -> Iterator[Path]:
    """Yield .md paths excluding framework/system directories.

    Excludes any path that has an ancestor named in EXCLUDED_DIRS or starting
    with a dot. Used by every backend that walks the vault, so search/index
    results stay consistent with vault_stats/list_recent_notes.
    """
    for p in vault_root.rglob("*.md"):
        rel_parts = p.relative_to(vault_root).parts
        if any(part in EXCLUDED_DIRS or part.startswith(".") for part in rel_parts[:-1]):
            continue
        yield p
