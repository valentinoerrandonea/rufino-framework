from pathlib import Path

from rufino.engine.query.api import QueryLayer


_EXCLUDED_DIRS = frozenset({"_meta", ".obsidian", ".git", ".trash", "node_modules"})


def _iter_user_notes(vault_root: Path):
    """Yield .md paths excluding framework/system directories."""
    for p in vault_root.rglob("*.md"):
        rel_parts = p.relative_to(vault_root).parts
        if any(part in _EXCLUDED_DIRS or part.startswith(".") for part in rel_parts[:-1]):
            continue
        yield p


def search_vault(ql: QueryLayer, *, query: str, mode: str = "hybrid", k: int = 10) -> list[str]:
    results = ql.search(query, mode=mode, k=k)
    return [r.relative_path for r in results]


def find_note(ql: QueryLayer, *, query: str) -> str | None:
    results = ql.search(query, mode="hybrid", k=1)
    return results[0].relative_path if results else None


def list_triples_for_node(
    ql: QueryLayer, *, node: str, relation: str, reverse: bool = True,
) -> list[str]:
    results = ql.traverse(node=node, relation=relation, depth=1, reverse=reverse)
    return [r.relative_path for r in results]


def read_note(ql: QueryLayer, *, relative_path: str) -> str:
    raw = ql.vault_root / relative_path
    if raw.is_symlink():
        raise ValueError(f"Path {relative_path!r} is a symlink (not allowed)")
    target = raw.resolve()
    vault_resolved = ql.vault_root.resolve()
    try:
        target.relative_to(vault_resolved)
    except ValueError:
        raise ValueError(f"Path {relative_path!r} resolves outside vault")
    if not target.is_file():
        raise ValueError(f"Path {relative_path!r} is not a regular file")
    try:
        return target.read_text()
    except UnicodeDecodeError as e:
        raise ValueError(f"Path {relative_path!r} is not valid UTF-8: {e}") from e


def vault_stats(ql: QueryLayer) -> dict:
    notes = list(_iter_user_notes(ql.vault_root))
    return {
        "note_count": len(notes),
        "vault_path": str(ql.vault_root),
    }


def list_recent_notes(ql: QueryLayer, *, k: int = 10) -> list[str]:
    notes = sorted(_iter_user_notes(ql.vault_root),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    return [str(p.relative_to(ql.vault_root)) for p in notes[:k]]
