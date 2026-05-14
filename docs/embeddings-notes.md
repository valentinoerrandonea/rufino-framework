# Embeddings vault-wide — notas operativas (Fase 4)

Búsqueda semántica sobre todo el vault de Obsidian usando **Ollama local** +
**sqlite-vec**. Sin red, sin costos, sin API keys.

## Stack

- **Modelo**: `nomic-embed-text` (768 dim, ~270 MB).
- **Backend**: Ollama HTTP en `http://localhost:11434/api/embeddings`.
- **Storage**: SQLite + extensión `sqlite-vec` (vía `pip install sqlite-vec`,
  más portable que la fórmula de brew y carga la extensión vía Python).
- **Lenguaje**: Python 3 (stdlib + `sqlite_vec`).
- **DB**: `${RUFINO_VAULT_PATH}/_meta/embeddings.sqlite` (no se commitea — está
  bajo el vault, fuera del repo).

## Setup (one-time)

```bash
# Ollama (si todavía no está):
brew install ollama
ollama pull nomic-embed-text   # ~270 MB

# Python deps:
pip3 install --break-system-packages sqlite-vec
```

El wrapper `rufino-build-embeddings.sh` auto-instala `sqlite-vec` si falta.
`ollama serve` se levanta automáticamente si no está corriendo cuando arranca el build.

## Uso

```bash
# Build inicial / re-sync incremental (idempotente):
claude/scripts/rufino-build-embeddings.sh

# Re-indexar una sola nota (watcher manual):
claude/scripts/rufino-build-embeddings.sh --only "$RUFINO_VAULT_PATH/proyectos/umbru/overview.md"

# Buscar:
claude/scripts/rufino-search-embeddings.sh "umbru matching arquitectura"
claude/scripts/rufino-search-embeddings.sh "musica alice in chains" -k 5
claude/scripts/rufino-search-embeddings.sh "decision rufino" --json
```

## Cómo funciona

1. Walk recursivo del vault, skipping `.obsidian`, `_meta`, `_trash`, `_archive`.
2. Por cada `.md`:
   - Strip frontmatter YAML.
   - SHA-256 del body. Si el hash matchea lo guardado → skip (idempotencia).
   - Si cambió o es nuevo: borrar entries previas y re-embed.
3. Notas **> 8 KB**: split en chunks de 4 KB con overlap de 200 chars. Cada
   chunk es una row distinta con `path = "ruta.md#chunk-N"`. El consumer dedup
   por path canónico si quiere.
4. Embeddings se guardan en una virtual table de sqlite-vec (`notes_vec`),
   linkeada por `rowid` a la tabla regular `notes` (metadata).

## Schema

```sql
CREATE TABLE notes (
    rowid INTEGER PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,    -- "subdir/file.md" o "subdir/file.md#chunk-N"
    mtime INTEGER NOT NULL,
    content_hash TEXT NOT NULL,    -- sha256 del body (sin frontmatter)
    title TEXT,                    -- primer H1 o filename
    chars INTEGER,
    indexed_at INTEGER NOT NULL
);

CREATE VIRTUAL TABLE notes_vec USING vec0(
    embedding FLOAT[768]
);
```

## Búsqueda — query SQL

```sql
SELECT n.path, n.title, v.distance
FROM notes_vec v
JOIN notes n ON n.rowid = v.rowid
WHERE v.embedding MATCH ? AND k = 10
ORDER BY v.distance;
```

`v.distance` es coseno (menor = más cercano).

## Decisiones técnicas

- **`nomic-embed-text` vs alternativas más grandes**: 768d, abierto, gratis,
  CPU-friendly. Para un vault de ~800 notas alcanza y sobra. Si más adelante
  Val quiere mejor recall en español, probar `bge-m3` (1024d, mejor multilingual).
- **sqlite-vec via pip**: la extensión `.dylib` viene en el wheel, así que un
  `pip install` es self-contained. La fórmula de brew tarda más en aparecer y
  no funciona en sandboxes restringidos.
- **Chunking simple por chars**: no tokenizamos. `nomic` corta a 8192 tokens
  internos; 4 KB de chars es ~1000 tokens, cómodo. Overlap de 200 chars cubre
  límites de párrafo sin inflar el índice.
- **Hash sobre body sin frontmatter**: el frontmatter cambia (mtime, etc.) sin
  cambiar contenido. Hashear sin frontmatter evita re-embed innecesario.
- **`ollama serve` auto-start**: si Ollama no responde, el script intenta
  levantarlo con `Popen` + `start_new_session=True`. Si no hay binario, falla
  con mensaje claro.
- **WAL + synchronous=NORMAL**: buena perf con cero riesgo para este uso
  (single-writer, no transactional).

## Performance

Vault de ~800 notas, M-series Mac, CPU:
- Cold build (todo nuevo): ~40-60s.
- Re-run sin cambios: ~1s (todo skipped por hash).
- Una sola nota (`--only`): <1s.

DB size después del build inicial: ~3-5 MB.

## Watcher incremental

`--only <path>` re-indexa una sola nota. Se puede integrar con un fsevents
watcher (fswatch / chokidar) más adelante, pero por ahora el use case más
común es: post-process en `rufino-process-single.sh` llama a
`rufino-build-embeddings.sh --only $note` cuando se filea un fact.

## Failure modes conocidos

- **Ollama no responde**: el script lo levanta. Si tarda >15s, hay que iniciarlo
  a mano.
- **Modelo no instalado**: `ollama pull` se dispara automático. Requiere red la
  primera vez.
- **Dim mismatch**: si alguien cambia `OLLAMA_MODEL`, el script chequea contra
  `EMBED_DIM=768` y aborta. Para cambiar de modelo: borrar la DB y rebuild.
- **`sqlite_vec` no importable**: el wrapper `.sh` lo instala automáticamente.

## Integración con MCP ask-rufino (agente paralelo)

El MCP `ask-rufino` (otro agente Fase 4) consume esta DB read-only:
- Mismo schema, misma path.
- Endpoint: `tool: ask_rufino(query: str) -> list[{path, title, distance, snippet}]`.
- El MCP carga `sqlite_vec` igual que este script; no toca `notes_vec` para
  escritura.
