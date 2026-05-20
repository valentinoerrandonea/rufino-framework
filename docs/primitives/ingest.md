# Ingest engine

Trae data de fuentes externas y la normaliza al vault. Es el punto de entrada para todo lo que no escribís a mano.

## Cuándo usar Ingest

- **Fuentes con API o feed:** Drive, GitHub, Calendar, Spotify, GMail, WhatsApp backup, Belo, etc.
- **Folders watched:** una carpeta donde tirás PDFs / capturas y querés que entren al inbox.
- **Webhooks:** algo que te empuja data (poll-based o push-based vía un endpoint local).

Si solo querés escribir notas a mano dentro del vault, **no necesitás Ingest** — escribilas directo y dejá que Process las augmente.

## Tres `output_mode`

| Mode | Output | Pasa por Process? | Cuándo usar |
|---|---|---|---|
| `emit_fact` | Records atómicos estructurados en `<source>/facts/<slug>.md` | No (queryable directo) | Eventos discretos con schema fijo: commits, plays, transacciones, mensajes |
| `import_raw` | Docs largos sin estructura en `inbox/` | Sí — invoca el Process adapter declarado en `process_with` | PDFs, papers, contratos, capturas largas — todo lo que necesita LLM |
| `emit_augmented` | Streaming directo a Process sin paso intermedio en disco | Sí (integrado) | Transcripts en vivo, scrapes donde el raw no tiene valor |

**v0.2.0:** los tres modos están wireados. `emit_augmented` streamea cada record directamente al Process adapter declarado en `process_inline_with` (modo light — tags + processing-log, sin LLM ni adapter dir).

## Manifest schema

```yaml
adapter_name: <kebab-case>            # único; debe matchear el dir name
source_name: <slug>                   # informativo (ej: gdrive, github, spotify)
schedule: "<cron-expression>"         # cuándo el scheduler dispara este adapter

auth:
  type: oauth2 | api_key | none
  keychain_service: <slug>            # ej: rufino-belo-oauth (si OAuth)
  refresh_endpoint: <url>             # endpoint de refresh OAuth si aplica

output_mode: emit_fact | import_raw | emit_augmented

# === emit_fact-specific ===
emits: [<entity_type>, ...]
fact_schema:
  <field>: <type>                     # string | number | datetime | enum[...]
destination:
  facts: <path-template>              # ej: belo/facts/<YYYY-MM-DD>-<id>.md
  raw: <path-template>                # opcional: guardar el JSON crudo
dedup_by: <field-name>                # ej: id

# === import_raw-specific ===
target_inbox: <relative-path>         # ej: rufino/inbox/
process_with: <process-adapter-name>  # ej: apunte-clase
trigger: immediate | defer            # default: immediate

# === emit_augmented-specific ===
process_inline_with: <process-adapter-name>  # required

# === opcional ===
transform_hook: ./transform.py        # ejecutado entre fetch y write (v0.2.0+)
```

## Helpers expuestos al adapter

Disponibles en `rufino.helpers.v1`:

- `oauth_flow(service, refresh_endpoint)` — flujo de refresh; devuelve el token actualizado.
- `keychain_secret(name)` — lee secret del Keychain por service name.
- `cursor_persist(name)` — guarda y lee el cursor del adapter (incremental fetch).
- `dedup_check(slug)` — chequea si ya emitimos este slug; mantiene set persistido.
- `fact_validate(record, schema)` — valida un dict contra el `fact_schema` declarado.

## Lifecycle de un run

1. **Scheduler dispara.** El cron del manifest se materializa a `launchd` (macOS) / `cron` o `systemd` (Linux) durante el install. Cuando dispara → ejecuta `rufino ingest <adapter_dir> --vault X --state-dir Y`.
2. **Auth.** Si `auth.type=oauth2`, refresh del token vía Keychain → si expiró, llama al `refresh_endpoint`.
3. **Cursor.** Lee el cursor persistido (`~/.rufino/state/<source_name>/cursor.json`).
4. **Fetch.** Si `fetcher.py` existe, lo carga vía `importlib` y llama `fetch(cursor)` — yields records. Si no existe, usa fetcher genérico.
5. **Validate.** Cada record contra `fact_schema`.
6. **Dedup.** Skip si `dedup_by` field ya está en el seen set.
7. **Write.** Según `output_mode`:
   - `emit_fact`: escribe `destination.facts` (con frontmatter del schema) y opcionalmente `destination.raw` con el JSON.
   - `import_raw`: escribe en `target_inbox` y notifica al Process adapter declarado en `process_with` (trigger immediate por default).
8. **Persist cursor.** Solo si `errors == 0` — esto es **clave** para idempotencia.

## CLI

```bash
rufino ingest <adapter_dir> --vault <X> --state-dir <Y>
```

Output:

```
adapter=<name> emitted=<N> skipped=<N> errors=<N>
```

Si `errors > 0`, cada uno sale a stderr. El cursor no avanza — un próximo run reintenta desde el mismo punto.

## Ejemplo: adapter completo

`manifest.yaml`:

```yaml
adapter_name: belo
source_name: belo
schedule: "*/30 * * * *"
auth:
  type: oauth2
  keychain_service: rufino-belo-oauth
  refresh_endpoint: https://api.belo.app/oauth/refresh

output_mode: emit_fact
emits: [transaccion]

fact_schema:
  id: string
  monto: number
  moneda: enum[ARS, USD, USDT]
  fecha: datetime
  cuenta: string
  contraparte: string

destination:
  facts: belo/facts/<YYYY-MM-DD>-<id>.md
  raw: belo/raw/<id>.json
dedup_by: id
```

`fetcher.py`:

```python
from typing import Iterator
from rufino.helpers.v1 import keychain_secret
import requests

def fetch(cursor: str | None) -> Iterator[dict]:
    token = keychain_secret("rufino-belo-oauth")
    params = {"since_id": cursor} if cursor else {}
    response = requests.get(
        "https://api.belo.app/v1/transactions",
        headers={"Authorization": f"Bearer {token}"},
        params=params,
    )
    response.raise_for_status()
    for tx in response.json()["transactions"]:
        yield {
            "id": tx["id"],
            "monto": tx["amount"],
            "moneda": tx["currency"],
            "fecha": tx["date"],
            "cuenta": tx["account"],
            "contraparte": tx["counterparty"],
        }

def next_cursor(record: dict) -> str:
    return record["id"]
```

## Validador del manifest

Bloquea install (errors) o loggea (warnings):

- **Errors:** schema YAML mal formado, required field faltante, `output_mode` desconocido, `destination` path absoluto, `process_with` apunta a adapter inexistente, `keychain_service` ya en uso por otro adapter, `dedup_by` no está en `fact_schema`, `transform_hook` declarado pero archivo no existe / no ejecutable.
- **Warnings:** `auth.type=none` con `output_mode=emit_fact` (probable typo), `schedule` muy frecuente (<5 min — riesgo de rate limit).

## Estado v0.2.0

- ✅ `emit_fact` — operativo
- ✅ `import_raw` — operativo (push immediato al Process declarado en `process_with`)
- ✅ `emit_augmented` — streaming inline a Process en modo light
- ✅ `transform_hook` — invocado entre fetch y write con graceful degrade ante errores
- ✅ Scheduler real — `rufino install-ingest <adapter>` materializa el cron a `launchd` (macOS) / `cron` (Linux)

## Referencia

- Shape "worker adapter": [`../adapters/worker-adapter.md`](../adapters/worker-adapter.md)
- Cómo escribir uno: [`../writing-adapters.md`](../writing-adapters.md#ingest-adapter)
