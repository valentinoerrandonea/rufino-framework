from rufino.engine.query.api import QueryLayer


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
    target = (ql.vault_root / relative_path).resolve()
    vault_resolved = ql.vault_root.resolve()
    try:
        target.relative_to(vault_resolved)
    except ValueError:
        raise ValueError(f"Path {relative_path!r} resolves outside vault")
    return target.read_text()


def vault_stats(ql: QueryLayer) -> dict:
    notes = list(ql.vault_root.rglob("*.md"))
    return {
        "note_count": len(notes),
        "vault_path": str(ql.vault_root),
    }


def list_recent_notes(ql: QueryLayer, *, k: int = 10) -> list[str]:
    notes = list(ql.vault_root.rglob("*.md"))
    notes.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [str(p.relative_to(ql.vault_root)) for p in notes[:k]]
