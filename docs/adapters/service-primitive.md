# Service primitive (no adapter)

La **Query layer** no tiene shape de adapter — es una API pura del framework. Cualquier consumidor (CLI, MCP, Output adapter, Wizard) la importa directamente.

```python
from rufino.engine.query.api import QueryLayer

ql = QueryLayer(vault_root=path, embedder=embedder)
ql.rebuild_indices()

results = ql.search("regresión", mode="hybrid", k=10)
relations = ql.traverse(node="ml-i", relation="tema-de", depth=1, reverse=True)
```

## Por qué no tiene adapter

Los adapters existen para configurar comportamiento específico del vertical. La búsqueda y traversal del grafo son operaciones universales: no cambian entre verticales. Forzar un manifest sería ceremonia sin valor.
