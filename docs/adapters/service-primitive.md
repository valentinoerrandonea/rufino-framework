# Service primitive (sin adapter)

La **Query layer** no tiene shape de adapter — es una API pura del framework. Cualquier consumidor (CLI, MCP server, Output adapter, wizard) la importa directamente.

```python
from rufino.engine.query.api import QueryLayer

ql = QueryLayer(vault_root=path, embedder=embedder)
ql.rebuild_indices()

results = ql.search("regresión", mode="hybrid", k=10)
relations = ql.traverse(node="ml-i", relation="tema-de", depth=1, reverse=True)
note = ql.read_note("apuntes/ml-i/2026-05-17.md")
```

## Por qué no tiene adapter

Los adapters existen para configurar **comportamiento específico del vertical**. La búsqueda y el traversal del grafo son operaciones **universales**: no cambian entre verticales — buscar "X" en notas de facultad y buscar "X" en notas de finanzas hace lo mismo conceptualmente.

Forzar un manifest declarativo de la API sería ceremonia sin valor: ¿qué configurarías? El path al vault ya viene del flag `--vault`. El embedder ya viene como dependencia. Los backends están todos siempre disponibles.

## Consumers

| Consumer | Cómo invoca |
|---|---|
| **CLI `rufino query`** | Modo lexical operativo. Semantic/hybrid exits 2 hasta embedder real. |
| **MCP server `ask-rufino`** | Expone 6+ tools que llaman a la API. |
| **Output adapters** | Vía `query_vault()` helper. |
| **Wizard** | Para chequear vault state al inicio del bootstrap. |

## Cuándo sí necesitarías un adapter de Query

Hipotético — no es el caso ahora. Si en algún momento la búsqueda **sí** dependiera del vertical (ej: el ranking de resultados varía según vertical, o cada vertical tiene su propio embedder porque su dominio es muy específico), tendría sentido tener `query/<vertical_name>/manifest.yaml` declarando esos parámetros. Pero v1 no lo necesita — los backends genéricos son suficientes para todos los verticales target.

## Referencia

- Primitive: [`../primitives/query.md`](../primitives/query.md)
- API completa: `src/rufino/engine/query/api.py`
