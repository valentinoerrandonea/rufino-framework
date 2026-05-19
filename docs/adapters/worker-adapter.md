# Worker adapter

Shape de adapter usado por **Ingest**, **Process** y **Output**. Es el shape más rico — los 3 primitives corren código, llaman LLM, producen output, y a veces necesitan transformación determinista.

## Estructura del filesystem

```
~/.rufino/adapters/<primitive>/<adapter_name>/
├── manifest.yaml           # required — declara contrato del adapter
├── prompt.md               # required para Process; opcional para Ingest emit_augmented
├── template.md             # required para Output
├── fetcher.py              # opcional — Ingest con fetch custom
└── transform.py            # opcional — hook de código determinista (deferido en v0.0.2)
```

`adapter_name` es kebab-case y debe matchear el dir name + el campo `adapter_name` del manifest.

## Manifest

Cada primitive define sus campos requeridos en `manifest.yaml`. Schemas detallados:

- [Ingest](../primitives/ingest.md#manifest-schema)
- [Process](../primitives/process.md#manifest-schema)
- [Output](../primitives/output.md#manifest-schema)

Reglas comunes a todos:

- **Schema YAML válido** (parsed con `yaml.safe_load`).
- **`adapter_name` kebab-case** y matchea el dir name.
- **Paths siempre relativos** al vault (`destination_path`, `destination.facts`, `destination.raw`, `path` en delivery, `target_inbox`) — el validador rechaza absolutos o paths con `..` que escapan.
- **`triple_vocabulary` no usa keywords reservados** del framework (`type`, `id`, `created`, `updated`, `tags`).
- **`tag_axes` no overlapean** entre sí.

## prompt.md (Process; opcional Ingest emit_augmented)

Markdown con placeholders `${var}` que el dispatcher reemplaza antes de mandar al LLM:

- `${note_body}` — contenido crudo de la nota
- `${context.<injector_name>}` — output de cada `context_injector` declarado
- `${triple_vocabulary}` — lista permitida (string)
- `${output_schema}` — schema esperado del output

Convención: estructurar el prompt en secciones (apunte crudo / contexto / vocabulario / reglas / output). Eso le da a Claude estructura mental clara.

## template.md (Output)

jinja2 con `StrictUndefined` — vars no declaradas tiran `UndefinedError` (no silent default). Vars disponibles:

- Cada `query[i].name` del manifest → lista de NoteRef
- Helpers: `today()`, `last_monday()`, `last_n_days(n)`, `last_1on1(person)`, etc.
- Si `trigger.type=on_event`: el payload del event como `event.*`

## fetcher.py (Ingest, opcional)

Si tu Ingest necesita lógica de fetch custom (típico para casi todos), creá un `fetcher.py` en el mismo dir:

```python
from typing import Iterator
from rufino.helpers.v1 import keychain_secret

def fetch(cursor: str | None) -> Iterator[dict]:
    """
    Yield records starting at `cursor`. Each must match the
    `fact_schema` declared in manifest.yaml.
    """
    ...

def next_cursor(record: dict) -> str:
    """Return the cursor to persist after processing `record`."""
    return record["id"]
```

El runner se carga vía `importlib`, llama a `fetch(cursor)`, valida cada record contra `fact_schema`, dedupea, escribe al vault, y persiste el cursor.

Si tu adapter no tiene `fetcher.py`, el runner usa un fetcher genérico para fuentes simples (file watcher, glob).

## transform.py (deferido)

**Estado en v0.0.2:** el manifest acepta y parsea el campo `transform_hook: ./transform.py`, pero el framework **no invoca el script todavía**. Si lo declarás hoy, no se ejecuta.

### Planificado

Firma del hook (cuando se implemente):

```python
# transform.py
def transform(input_dict: dict) -> dict:
    """
    Called after the LLM call in Process, or after fetch in Ingest.
    Input via stdin JSON, output via stdout JSON.
    """
    # determinist computation:
    monto_ars = input_dict["monto"] * exchange_rate(input_dict["moneda"])
    return {**input_dict, "monto_ars": monto_ars}
```

### Sandbox planificado

- **Filesystem readonly** excepto el path declarado en `transform_writes_to:` del manifest.
- **Network bloqueado por default**; opt-in con `transform_needs_network: true` (loggea + requiere user OK al install).
- **Timeout** 60s default, configurable hasta 300s.
- **Resource limits** (Unix): `RLIMIT_AS 512 MB`, `RLIMIT_CPU 30s`.
- **Env restringido:** `PATH=/usr/bin`, `PYTHONPATH=<framework_helpers_v1>`.
- **Validador integrado:** smoke test con input dummy al instalar — si falla, bloquea install.

Implementación parcial en `src/rufino/runtime/sandbox.py` (base de subprocess con timeout); resto pendiente.

## batch_size (Process, opcional)

Solo aplica a Process. Controla cuántas notas procesa cada worker durante
`rufino process-batch`:

```yaml
batch_size: <int>                    # optional, default 10 — workers process
                                      # up to this many notes per spawn during
                                      # rufino process-batch
```

El planner parte grupos más grandes en sub-batches del tamaño declarado. Default 10.

## Validación

El framework valida cada manifest antes de cargar el adapter — al instalar el wizard, al correr `rufino ingest/process/output`, o al hacer `lint`. Errores bloquean operation; warnings se loggean.

Implementación de los validators:

- `src/rufino/engine/ingest/manifest.py:IngestManifestValidator`
- `src/rufino/engine/process/manifest.py:ProcessManifestValidator`
- `src/rufino/engine/output/manifest.py:OutputManifestValidator`

Todos extienden `ValidatorBase` en `src/rufino/runtime/validator_base.py`.

## Inmutabilidad

`WorkerAdapterManifest` parseado es recursivamente inmutable (`MappingProxyType` + tuplas + nested freeze). Si tu código intenta mutar un campo:

```python
manifest["new_field"] = "x"   # TypeError: 'mappingproxy' object does not support item assignment
```

Eso evita una clase entera de bugs donde un dispatcher mute state shared con su caller. Si necesitás derivar info, hacelo en una struct nueva.

## Errores comunes al escribir

| Error | Causa | Fix |
|---|---|---|
| `Path traversal rejected: <path>` | `destination_path` empieza con `/` o contiene `..` que escapa el vault | Usá path relativo, no escapes |
| `Triple vocabulary uses reserved keyword: type` | Pusiste `type` en `triple_vocabulary` | Renombrá la relación (ej: `categoria-de` en vez de `type`) |
| `Tag axes overlap: 'tema' vs 'topic'` | Dos axes que comparten formato | Elegí uno y rename consistentemente |
| `process_with references unknown adapter: apunte-clase` | Ingest declara `process_with: apunte-clase` pero no hay un Process adapter con ese nombre | Crear el adapter o corregir el nombre |
| `transform_hook declared but file not executable` | `transform.py` existe pero no tiene execute bit | `chmod +x transform.py` (cuando se cierre el sandbox wiring) |
| `Q&A template not found: materia_ambigua` | El Process adapter llama `ask_user("materia_ambigua")` pero el template no está instalado | Materializar el template en `~/.rufino/qa-templates/` |

## Lifecycle de carga de un adapter

```
1. CLI (rufino ingest/process/output) invocado con --adapter-dir
       ↓
2. Engine carga manifest.yaml con yaml.safe_load
       ↓
3. Validator del primitive corre validate(manifest)
       ↓ (Errors → InstallationError / RuntimeError; warnings → log)
4. Si Ingest + fetcher.py existe → importlib.import_module
5. Si Process + transform.py existe → defer (no invocado en v0.0.2)
6. Si Output → cargar template.md
       ↓
7. Dispatcher ejecuta el lifecycle del primitive
```

## Referencia

- Cómo escribir uno (con ejemplos): [`../writing-adapters.md`](../writing-adapters.md)
- Primitives:
  - [Ingest](../primitives/ingest.md)
  - [Process](../primitives/process.md)
  - [Output](../primitives/output.md)
