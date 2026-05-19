# Output dispatcher

Genera derivados del vault: digests, reportes, recomendaciones, alertas. Output toma data del vault (vía Query), la renderiza con un template, y la entrega por un channel.

## Cuándo usar Output

- **Digests recurrentes:** resumen semanal/mensual de actividad.
- **Reportes triggered:** bio mensual de una persona, year-review, post-mortem.
- **Alertas:** aviso 24h antes de examen, notificación cuando un OKR no se mueve.
- **Hand-offs:** meeting prep, reportes a stakeholders.

Si solo querés **consultar** el vault, usá Query directo — no necesitás Output. Output es para producir **entregables persistidos o entregados a un channel externo**.

## Triggers

| Tipo | Cuándo dispara | Schema |
|---|---|---|
| `cron` | Schedule cron | `trigger: { type: cron, expression: "0 18 * * 5" }` |
| `on_event` | Cuando Process emite un evento | `trigger: { type: on_event, event: <event-name>, filter: "<expression>" }` |

`on_event` se suscribe a eventos del Process dispatcher (`on_new(<note_type>)`) o de fuentes externas (`calendar_event`, `new_fact`, etc.). El `filter` es una expression que se evalúa contra el event payload.

## Manifest schema

```yaml
adapter_name: <kebab-case>
trigger:
  type: cron | on_event
  expression: "<cron>"                # si type=cron
  event: <event-name>                 # si type=on_event
  filter: "<expression>"              # si type=on_event

query:
  - name: <var-name>                  # nombre que aparece en el template
    expression: "<query>"             # ej: "type=apunte_clase AND created >= last_monday()"

template: ./templates/<name>.md       # path al template jinja2

delivery:
  - channel: file
    path: "<path-template>"           # relativo al vault
  - channel: email
    to: "<addr>"
    subject: "<jinja2-template>"
  - channel: webhook
    url: "<https-url>"
    method: POST                      # default POST
  - channel: push
    title: "<jinja2>"
    body: "<jinja2>"
```

## Channels built-in

| Channel | Schema en `delivery` | Notas |
|---|---|---|
| `file` | `{ channel: file, path: "<rel-path>" }` | Path resuelto contra el vault root. **Path traversal bloqueado** (defensa profunda con `resolve()` + ancestor check). |
| `email` | `{ channel: email, to: "...", subject: "..." }` | SMTP via Keychain (`smtp-rufino` service por default). Timeout 30s. |
| `webhook` | `{ channel: webhook, url: "<https-only>", method: POST }` | Solo `http(s)://` schemes — rechaza file://, javascript://, etc. Timeout 30s. |
| `push` | `{ channel: push, title: "...", body: "..." }` | macOS via `osascript` (escape de `\`, `"`); Linux via `notify-send` con args explícitos para evitar flag injection. |

Cada channel valida sus inputs **antes** de la entrega. Errores de delivery se colectan en `result.errors` sin tirar el dispatcher entero — un email que falla no bloquea el escribir al file.

## Helpers del runtime

- `query_vault(expression)` — invoca la Query layer; devuelve lista de notas.
- `render_template(template_path, context)` — jinja2 con `StrictUndefined` (templates con vars no declaradas tiran error).
- `deliver(channel, content, meta)` — abstracción channel-agnostic.

## Pipeline de un run

```
1. Resolver queries declaradas en el manifest
       ↓ (cada query devuelve lista de notas / facts)
2. Cargar template
       ↓
3. Render template con queries como variables + helpers (today(), last_monday(), etc.)
       ↓ (StrictUndefined: var faltante tira UndefinedError loud)
4. Para cada delivery declarada:
       ├─→ Validar channel + inputs (path traversal, scheme, escape)
       ├─→ Llamar channel.deliver(rendered_content, meta)
       └─→ Si falla, agregar al result.errors (no tira)
       ↓
5. result = OutputResult(adapter_name, deliveries, errors)
```

## CLI

```bash
rufino output <adapter_dir> --vault <X>
```

Output:

```
adapter=<name> deliveries=<N> errors=<N>
```

Si `errors > 0`, salen a stderr.

**Nota:** el Query adapter usado por la CLI (`_LexicalQueryAdapter`) opera sobre el backend lexical. Output adapters no consumen `semantic`/`hybrid` directamente — si tu query expression necesita similitud semántica, usá `rufino query --mode semantic` desde un trigger externo y pasale el resultado al output (v0.2.0 mantiene esta separación).

## Ejemplo: digest-semanal

`manifest.yaml`:

```yaml
adapter_name: digest-semanal
trigger:
  type: cron
  expression: "0 18 * * 5"          # viernes 18:00

query:
  - name: notas_semana
    expression: "created >= last_monday() AND type IN [apunte_clase, paper]"
  - name: topics_nuevos
    expression: "concept_promotions WHERE created >= last_monday()"

template: ./templates/digest-semanal.md

delivery:
  - channel: email
    to: "beto@example.com"
    subject: "Digest semanal: {{ topics_nuevos | length }} topics nuevos"
  - channel: file
    path: "digests/{{ today() }}-semanal.md"
```

`templates/digest-semanal.md`:

```markdown
# Digest semanal — {{ today() }}

## Esta semana viste

{% for nota in notas_semana %}
- [[{{ nota.slug }}]] ({{ nota.materia }}) — {{ nota.summary }}
{% endfor %}

## Topics nuevos detectados

{% for topic in topics_nuevos %}
- **{{ topic.name }}** ({{ topic.count }} menciones) — promovido a [[conceptos/{{ topic.slug }}]]
{% endfor %}
```

## Ejemplo: meeting-prep (on_event)

```yaml
adapter_name: meeting-prep
trigger:
  type: on_event
  event: calendar_event
  filter: "tag = '1:1' AND starts_in_hours < 24"

query:
  - { name: notas_persona,      expression: "tag=persona/<event.attendee> AND created >= last_1on1(<event.attendee>)" }
  - { name: feedback_pendiente, expression: "type=feedback AND target=persona/<event.attendee> AND status=pending" }
  - { name: okrs_persona,       expression: "type=okr AND owner=persona/<event.attendee> AND active=true" }

template: ./templates/meeting-prep.md

delivery:
  - channel: file
    path: "meetings/<event.attendee>/<YYYY-MM-DD>-1on1.md"
  - channel: email
    to: "manager@empresa.com"
    subject: "1:1 prep: <event.attendee>"
```

## Validador del manifest

- **Errors:**
  - `trigger.type` no es `cron` o `on_event`
  - `trigger.expression` cron inválido (out of range fields, fields faltantes)
  - `query[i]` sin `name` o sin `expression`
  - `template` apunta a archivo inexistente
  - `delivery[i].channel` desconocido
  - `delivery[i].path` absoluto o con `..` que escapa
  - `delivery[i].url` con scheme no http(s)
  - `delivery[i]` (push) sin `title`
- **Warnings:**
  - Template tiene vars no declaradas en `query` (StrictUndefined va a tirar at runtime)
  - `trigger.expression` muy frecuente para un cron (riesgo de output spam)

## Inmutabilidad

`OutputAdapterManifest` parseado es recursivamente inmutable. `OutputResult` también frozen. Si tu channel custom intenta mutar el manifest, tira `TypeError`.

## Custom channels

Si necesitás un channel que no está built-in (ej: Slack, Discord, push iOS), implementá la interfaz:

```python
from rufino.engine.output.channels.base import OutputChannel

class SlackChannel(OutputChannel):
    name = "slack"

    def deliver(self, content: str, meta: dict) -> None:
        webhook_url = meta["webhook_url"]
        # ... HTTP POST ...

    def validate(self, delivery: dict) -> list[str]:
        errors = []
        if "webhook_url" not in delivery:
            errors.append("slack channel requires 'webhook_url'")
        return errors
```

Registralo en el dispatcher antes de la corrida:

```python
from rufino.engine.output.dispatcher import dispatch_output
channels = {
    "file": FileChannel(vault_root=...),
    "slack": SlackChannel(),
}
dispatch_output(adapter_dir=..., query=..., channels=channels, ...)
```

## Estado v0.2.0

- ✅ `file`, `email`, `webhook`, `push` channels — operativos
- ✅ `trigger.type: cron` — operativo
- ✅ `trigger.type: on_event` — engine listo, requiere wiring con publisher de eventos (Process emite `on_new(<note_type>)`)
- ✅ jinja2 StrictUndefined renderer — operativo
- ✅ Lexical Query backend operativo; `semantic`/`hybrid` opt-in vía `rufino enable-embeddings`

## Referencia

- Shape "worker adapter": [`../adapters/worker-adapter.md`](../adapters/worker-adapter.md)
- Cómo escribir uno: [`../writing-adapters.md#output-adapter`](../writing-adapters.md#output-adapter)
