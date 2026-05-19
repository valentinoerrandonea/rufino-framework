# Query layer

API unificada de lectura sobre el vault. Es un **service primitive** — no tiene shape de adapter. Cualquier consumidor (CLI, MCP server, Output adapter, wizard) la importa directamente.

## Por qué no hay adapters de Query

Los adapters existen para configurar **comportamiento específico del vertical**. La búsqueda y traversal del grafo son operaciones **universales** — no cambian entre verticales. Forzar un manifest declarativo de la API sería ceremonia sin valor.

## API

```python
from rufino.engine.query.api import QueryLayer

ql = QueryLayer(vault_root=Path("/Users/beto/facultad"), embedder=embedder)
ql.rebuild_indices()                  # idempotente; reconstruye DBs derivadas

# Búsqueda
results: list[NoteRef] = ql.search(
    query="regresión logística",
    mode="lexical" | "semantic" | "hybrid",
    k=10,
)

# Traversal del grafo
related: list[NoteRef] = ql.traverse(
    node="ml-i",
    relation="tema-de",
    depth=1,
    reverse=True,                     # incoming en vez de outgoing
)

# Lectura de una nota
note: Note = ql.read_note("apuntes/ml-i/2026-05-17-regresion.md")
```

## Modos de búsqueda

| Mode | Backend | Notas |
|---|---|---|
| `lexical` | ripgrep sobre los markdown del vault | Exact match / regex. Rápido. Operativo en v0.0.2. |
| `semantic` | Embeddings (Ollama + `nomic-embed-text`) + sqlite-vec | Similitud semántica. **Requiere embedder real — placeholder en v0.0.2 tira NotImplementedError.** |
| `hybrid` | Combinación de lexical + semantic con re-ranking | Default cuando aterrice el embedder. |

## Backends

### Lexical (ripgrep)

`engine/query/backends/lexical.py`:

- Usa `rg --json` para queries flexibles.
- Filtra fuera de los system dirs (`_meta/`, `.obsidian/`, `.git/`) via `iter_user_notes()` + `EXCLUDED_DIRS` centralizado en `engine/query/filters.py`.
- `--` separator antes del query string → queries con prefix `-` no crashean.
- Globs `!_meta/` `!.*/` para excluir basura.

### Semántica (embeddings)

`engine/query/backends/semantic.py`:

- Embeddings persistidos en `<vault>/_meta/embeddings.sqlite` con `sqlite-vec`.
- Default model: `nomic-embed-text` via Ollama.
- File watcher reindexa al modificar notas (no implementado en v0.0.2 — requiere primer rebuild manual).

**Estado:** placeholder `_NoopEmbeddings` en `cli.py` — tira `NotImplementedError` si llega a `embed()`. El primitive está completo, solo falta wirear un embedder real.

### Grafo (SQLite triple store)

`engine/query/backends/graph.py`:

- Parsea el frontmatter `triples:` de cada nota → carga en SQLite (`<vault>/_meta/triples.sqlite`).
- Coerce defensivo: `entry["o"]` a `str()`, valida `entry["r"]` es string, rechaza None.
- Reverse traversal soportado (encontrar notas que apuntan **a** este nodo).

### Facetada

Predicado declarativo sobre frontmatter fields. Usado internamente por las queries de Output adapters:

```yaml
expression: "type=apunte_clase AND created >= last_monday() AND tags contains 'materia/ml-i'"
```

## Consumers

| Consumer | Cómo invoca |
|---|---|
| **MCP server `ask-rufino-<slug>`** | Expone 6+ tools (`search_vault`, `read_note`, `traverse_relations`, `list_persons`, `list_concepts`, `vault_info`). Lanzado por Claude Code anfitrión. Registrado per-vault: cada vault recibe su propio entry en `~/.claude.json`. |
| **CLI `rufino query`** | Modo lexical operativo. `semantic`/`hybrid` exits 2 hasta que aterrice embedder. |
| **Output adapters** | Via `query_vault()` helper. |
| **Wizard inicial** | Para chequear si el vault ya tiene algo similar al adapter a generar. |

## CLI

```bash
rufino query "<query>" --vault <X> --mode {lexical|semantic|hybrid}
```

v0.0.2: solo `--mode lexical` funciona. Output: paths relativos al vault, uno por línea.

## MCP server

```bash
rufino mcp-server --vault <X> [--no-rebuild]
```

Por default rebuildea índices al startup (necesario en primer arranque para popular la DB). Después podés correr con `--no-rebuild` para arranque rápido.

Tools expuestos:

| Tool | Args | Output |
|---|---|---|
| `search_vault` | `query: str, mode: str = "hybrid", k: int = 10` | Lista de NoteRef con path + summary |
| `read_note` | `path: str` (relativo al vault) | Contenido completo de la nota |
| `traverse_relations` | `node: str, relation: str, depth: int = 1, reverse: bool = False` | Lista de NoteRef |
| `list_persons` | (no args) | Lista de personas registradas |
| `list_concepts` | (no args) | Lista de conceptos promocionados |
| `vault_info` | (no args) | Stats del vault (nota count, persona count, etc.) |

Schemas estrictos:
- `required` declarado por tool
- Args desconocidos filtrados (no se pasan al engine)
- `path` en `read_note` valida `is_absolute()` y rechaza con mensaje claro si el path es absoluto o se escapa del vault
- Symlinks rechazados (defensa contra escape via symlink)

## Indices (DBs derivadas)

Viven en `<vault>/_meta/`:

```
_meta/
├── embeddings.sqlite       # sqlite-vec embeddings
├── triples.sqlite          # triple store
└── lint-<YYYY-MM-DD>.json  # último reporte de lint
```

**Son siempre reconstruibles** desde el vault. Si una DB se corrompe, borrala y corré `ql.rebuild_indices()` — todo se rebuildea desde los markdown. El vault es la fuente de verdad; los indices son cache.

`rebuild_indices()` es atómico (tmp + rename) — no deja DB corrupta a mitad si el proceso muere.

## Encoding

Todos los `read_text()` usan `encoding="utf-8"` explícito. UTF-8-tolerante en lectura (errors=replace) — un archivo con bytes weirdos no rompe el rebuild.

## Limitaciones v0.2.0

- **Multi-hop traverse (`depth > 1`) raises NotImplementedError.** Forward y reverse están soportados ambos a `depth=1`; multi-hop queda diferido a v1.1.
- **Sin file watcher.** Los indices no se rebuildean automáticamente al modificar notas — necesitás correr `rebuild_indices()` o relanzar el MCP server con `--rebuild`.
- **Sin paginación.** `search()` devuelve hasta `k` resultados; queries con muchísimos matches pueden ser lentas (no es problema en vaults <10k notas).

## Referencia

- Shape "service primitive": [`../adapters/service-primitive.md`](../adapters/service-primitive.md)
