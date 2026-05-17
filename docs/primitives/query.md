# Query layer

API unificada de lectura. Service primitive — no tiene shape de adapter.

## API

```python
search(query: str, mode: "lexical" | "semantic" | "hybrid", k: int) → [NoteRef]
traverse(node: str, relation: str, depth: int, reverse: bool) → [NoteRef]
```

Backends: ripgrep (lexical), Ollama+cosine (semántico), SQLite triple store (grafo).

Ver [Plan 7](../superpowers/plans/2026-05-16-plan-7-query-layer-mcp.md).
