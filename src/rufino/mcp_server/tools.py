from pathlib import Path

from rufino.engine.query.api import QueryLayer
from rufino.engine.query.filters import iter_user_notes


def search_vault(ql: QueryLayer, *, query: str, mode: str = "auto", k: int = 10) -> list[str]:
    if mode == "auto":
        mode = "hybrid" if ql.embeddings_enabled() else "lexical"
    results = ql.search(query, mode=mode, k=k)
    return [r.relative_path for r in results]


def find_note(ql: QueryLayer, *, query: str) -> str | None:
    mode = "hybrid" if ql.embeddings_enabled() else "lexical"
    results = ql.search(query, mode=mode, k=1)
    return results[0].relative_path if results else None


def list_triples_for_node(
    ql: QueryLayer, *, node: str, relation: str, reverse: bool = False,
) -> list[str]:
    results = ql.traverse(node=node, relation=relation, depth=1, reverse=reverse)
    return [r.relative_path for r in results]


def read_note(ql: QueryLayer, *, relative_path: str) -> str:
    if Path(relative_path).is_absolute():
        raise ValueError(f"relative_path must be relative, got absolute {relative_path!r}")
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
        return target.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        raise ValueError(f"Path {relative_path!r} is not valid UTF-8: {e}") from e


def vault_stats(ql: QueryLayer) -> dict:
    notes = list(iter_user_notes(ql.vault_root))
    return {
        "note_count": len(notes),
        "vault_path": str(ql.vault_root),
    }


def list_recent_notes(ql: QueryLayer, *, k: int = 10) -> list[str]:
    notes = sorted(iter_user_notes(ql.vault_root),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    return [str(p.relative_to(ql.vault_root)) for p in notes[:k]]
