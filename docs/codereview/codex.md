# Code Review Codex - Rufino v0.2.0

Fecha: 2026-05-19
Rama revisada: `feat/v0.2.0`
Base de comparacion: `origin/main...HEAD`

## Resumen ejecutivo

La implementacion cubre una porcion grande del plan v0.2.0 y trae tests nuevos extensos, pero no esta lista para merge/release. Hay fallas bloqueantes en el flujo default del wizard/MCP y una incompatibilidad fuerte entre el schema nuevo del wizard y el manifest/runtime de Ingest `emit_fact`.

La mayor preocupacion es que el camino conservador prometido por el wizard ("sin embeddings, busqueda lexica") registra un MCP server que arranca con `--rebuild` por default y termina llamando al embedder `NoopEmbedder`, lo que rompe el MCP server de un vault recien materializado sin embeddings. Tambien hay comandos que el propio prompt del wizard instruye ejecutar sin `--state-dir`, pero la CLI lo requiere obligatoriamente.

## Hallazgos

### P0 - MCP server default roto cuando embeddings estan deshabilitados

Evidencia:
- `materialize_cmd` escribe `embeddings_enabled=False` por default y registra el MCP server con `mcp-server --vault ... --state-dir ...`: `src/rufino/cli.py:470-498`.
- `mcp_server_cmd` tiene `--rebuild=True` por default y siempre llama `ql.rebuild_indices()`: `src/rufino/cli.py:296-311`.
- `QueryLayer.rebuild_indices()` siempre ejecuta `self._sem.rebuild_index()`: `src/rufino/engine/query/api.py:28-31`.
- `SemanticBackend.rebuild_index()` llama `self.embedder.embed(text)` para cada nota: `src/rufino/engine/query/semantic.py:34-40`.
- `NoopEmbedder.embed()` levanta `NotImplementedError`: `src/rufino/runtime/embedder/resolve.py:15-21`.

Impacto:
El flujo default recomendado por el wizard registra un MCP server que falla al arrancar para vaults sin embeddings. Eso contradice la regla operativa de que el default sea lexical-only y deja inutilizable la feature distintiva "ask-rufino MCP" justo despues de materializar.

Reproduccion rapida:
`QueryLayer(vault_root=..., embedder=NoopEmbedder()).rebuild_indices()` levanta `NotImplementedError: embeddings no configurados...`.

Recomendacion:
Separar rebuild semantico de rebuild de grafo. Con `NoopEmbedder`, `mcp-server --rebuild` deberia reconstruir solo indices no semanticos o saltar semantic index con warning. Alternativamente, cambiar el default de `mcp-server` a no rebuild semantico cuando el embedder sea `NoopEmbedder`.

### P0 - Wizard `emit_facts` materializa manifests incompatibles con Ingest runtime

Evidencia:
- `spec_schema` valida `sources[].destination` como string para `emit_facts`: `src/rufino/wizard/spec_schema.py:188-196`.
- `materialize_ingest` copia ese `destination` directo al manifest: `src/rufino/wizard/adapter_materializers/ingest.py:82-89`.
- `parse_ingest_manifest` espera que `destination` sea mapping y hace `dest.get("facts")`: `src/rufino/engine/ingest/manifest.py:68-75`.
- `spec_schema` valida `dedup_by` como lista/tuple: `src/rufino/wizard/spec_schema.py:193-196`.
- `run_ingest` usa `manifest.dedup_by` como clave string: `src/rufino/engine/ingest/runner.py:127`.

Impacto:
El wizard puede aceptar una spec `emit_facts` que luego explota durante materializacion con `AttributeError: 'str' object has no attribute 'get'`. Si se cambia `destination` a mapping, el schema actual lo rechaza. Aun si se sortea eso, `dedup_by` como lista termina siendo incompatible con `fact[manifest.dedup_by]`.

Reproduccion rapida:
Una spec con `output_mode="emit_facts"`, `destination="facts.jsonl"` y `dedup_by=["id"]` pasa la validacion del wizard pero `materialize_ingest()` falla con `AttributeError`.

Recomendacion:
Alinear el contrato end-to-end. O el wizard debe exigir `destination: {facts: ..., raw: ...}` y `dedup_by: "id"`, o el parser/runtime de Ingest debe aceptar la nueva forma. Agregar test integrado `validate_spec -> materialize_ingest -> parse_ingest_manifest -> run_ingest` para `emit_facts`.

### P1 - El wizard instruye un comando de embeddings que la CLI rechaza

Evidencia:
- Prompt del wizard: despues de `detect-embeddings`, instruye `rufino enable-embeddings --vault <vault>`: `src/rufino/wizard/system_prompt_assembler.py:71-74`.
- Reglas operativas repiten el mismo comando sin `--state-dir`: `src/rufino/wizard/operative_rules.md:11`.
- La CLI marca `--state-dir` como requerido en `enable-embeddings`: `src/rufino/cli.py:333-340`.

Impacto:
Si el wizard sigue sus propias instrucciones, el comando falla por parametro faltante. Esto corta el flujo guiado para activar busqueda semantica.

Recomendacion:
Hacer `--state-dir` opcional con default `~/.rufino/state`, igual que `query` y `mcp-server`, o actualizar todos los prompts/reglas para pasar el mismo `state_dir` usado en `materialize`.

### P1 - La busqueda hibrida carga `sentence_transformers` en rutas de tests/MCP no mockeadas y puede abortar el proceso

Evidencia:
- `QueryLayer.search(..., mode="hybrid")` instancia `CrossEncoderReranker()` y llama `rerank()`: `src/rufino/engine/query/api.py:48-70`.
- `CrossEncoderReranker._load_model()` importa `sentence_transformers.CrossEncoder` y carga `BAAI/bge-reranker-base`: `src/rufino/runtime/embedder/cross_encoder.py:15-18`.
- Tests no mockeados llaman busqueda hibrida con embedder fake, por ejemplo `tests/test_query_api.py:46-63` y `tests/test_mcp_tools.py:137-149`.

Impacto:
La suite completa aborto localmente al importar `torch` via `sentence_transformers` en Python 3.14/Homebrew. Aunque esto puede ser de entorno, el problema de producto permanece: una busqueda hibrida puede cargar un modelo pesado o fallar por dependencias nativas en paths que antes eran livianos. En MCP, un tool call puede pagar ese costo o tumbar el proceso.

Resultado observado:
`pytest -q` avanzo hasta ~32%, registro fallos y luego termino con `Fatal Python error: Aborted` en `torch/__init__.py`, invocado desde `src/rufino/runtime/embedder/cross_encoder.py:17`.

Recomendacion:
Inyectar/cachear el reranker y mockearlo en tests que no estan probando rerank. Considerar un fallback mas amplio que `ImportError` para errores de carga del modelo, y no usar `hybrid` como default en herramientas que prometen funcionar sin setup pesado.

### P1 - Filtros de cron pueden borrar jobs por coincidencia de prefijo

Evidencia:
- `_filter_other_entries()` borra cualquier linea que contenga `# rufino-job:{job_id}` como substring: `src/rufino/runtime/scheduler/cron.py:88-93`.

Impacto:
Desinstalar `job_id="foo"` borra tambien una linea marcada `# rufino-job:foobar`, porque el marcador de `foo` es prefijo del marcador de `foobar`. Esto puede eliminar schedules de otros adapters/vaults si sus ids comparten prefijo.

Recomendacion:
Parsear el marcador exacto al final de linea o comparar el job id extraido despues de `_MARKER_PREFIX` con igualdad exacta.

### P2 - `install-ingest` persiste paths relativos en jobs de cron/launchd

Evidencia:
- El comando del job usa `str(adapter_dir)` y `str(vault_root)` tal como entraron por CLI: `src/rufino/cli.py:586-592`.

Impacto:
Si el usuario instala con paths relativos, cron/launchd ejecutara desde otro working directory y el job puede fallar por no encontrar adapter o vault. Esto es especialmente probable porque el wizard ofrece `rufino install-ingest <adapter_dir> --vault <vault>`.

Recomendacion:
Resolver `adapter_dir = adapter_dir.expanduser().resolve()` y `vault_root = vault_root.expanduser().resolve()` antes de construir `job_id` y `cmd`.

### P2 - `materialize --embeddings` marca embeddings como habilitados sin detectar prereqs ni construir indice

Evidencia:
- `materialize_cmd` escribe estado de embeddings segun el flag, pero no llama `detect_ollama()` ni `QueryLayer.rebuild_indices()`: `src/rufino/cli.py:441-477`.
- El comando dedicado `enable_embeddings_cmd` si detecta prereqs y reconstruye antes de escribir estado: `src/rufino/cli.py:345-363`.

Impacto:
El flag `--embeddings` puede dejar el vault en estado "enabled" aunque Ollama no este listo o el indice semantico no exista. Las consultas semanticas posteriores pueden fallar por conexion a Ollama o devolver resultados vacios hasta que algun rebuild ocurra.

Recomendacion:
Eliminar el flag de `materialize` o hacer que delegue en la misma logica atomica de `enable_embeddings_cmd`.

## Verificacion ejecutada

- `git diff --stat origin/main...HEAD`: 93 archivos, ~8278 inserciones.
- `pytest -q`: no completo; fallo por `ModuleNotFoundError: No module named 'mcp'` y luego aborto fatal importando `torch` via `sentence_transformers`.
- `pytest -q -x`: primer fallo aislado en `tests/test_mcp_server_smoke.py::test_server_builds_with_query_layer` por falta de paquete `mcp` en el entorno local.
- `pytest -q -x -k 'not mcp'`: primer fallo aislado en `tests/test_output_channel_webhook_push.py::test_webhook_posts_json` por DNS local de `example.com`; luego la corrida sin `-x` aborto por `sentence_transformers/torch`.
- Reproduccion manual de `NoopEmbedder + rebuild_indices`: confirma `NotImplementedError`.
- Reproduccion manual de `emit_facts` desde wizard schema hacia materializer: confirma `AttributeError` en `destination` string.

## Gaps de test recomendados

- Test integrado para vault materializado sin embeddings: `materialize -> mcp-server --rebuild` no debe fallar.
- Test integrado completo para `emit_facts`: `validate_spec -> materialize_ingest -> parse_ingest_manifest -> run_ingest`.
- Tests de CLI wizard commands reales: validar que los comandos escritos en `system_prompt_assembler.py` son aceptados por Click.
- Test de uninstall cron con ids prefijo: instalar `foo` y `foobar`, desinstalar `foo`, verificar que `foobar` queda.
- Tests que aseguren que `install-ingest` escribe paths absolutos en cron/launchd.
