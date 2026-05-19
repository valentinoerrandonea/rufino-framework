"""Per-vault slug derivation.

Single source of truth for the identifier used to name vault-specific artifacts
(hook scripts, /remember command, MCP server entry). Keeping this in one place
means the installer, the MCP register call, and the wizard all agree on the
slug for a given vault path.
"""
import re
from pathlib import Path


_SEPARATOR_RE = re.compile(r"[^a-z0-9]+")


def compute_vault_slug(vault_path: Path) -> str:
    """Derive a stable, filesystem-safe slug from a vault path's basename.

    Two vaults at different paths with the same basename will collide — the
    caller is responsible for keeping vault directory names unique on the
    same machine.
    """
    name = vault_path.expanduser().name
    slug = _SEPARATOR_RE.sub("-", name.lower()).strip("-")
    if not slug:
        raise ValueError(
            f"vault_path {vault_path!r} produces empty slug "
            f"(basename {name!r} normalized to nothing usable)"
        )
    return slug
