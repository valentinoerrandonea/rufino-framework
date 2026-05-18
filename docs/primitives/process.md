# Process pipeline

Augmenta notas crudas: frontmatter, body augmentado, triples tipados, tags por ejes, wikilinks, indices actualizados. Es **el corazón** del augmentation que define a Rufino.

## Cuándo dispara

- Cuando Ingest `import_raw` empuja una nota nueva al inbox (trigger immediate por default).
- Cuando un file watcher detecta un archivo nuevo en `<source_dir>` del manifest.
- Manualmente vía `rufino process <note>`.

## Modos

| Modo | Pipeline | Útil para |
|---|---|---|
| `full` | Pipeline completo (todos los 11 pasos) | Notas crudas que necesitan LLM + augmentation real |
| `light` | Solo update de indices + file move + frontmatter completion | Notas escritas a mano (por vos o Claude) que solo necesitan ser registradas + linkeadas |
| `lint` | Valida sin modificar | CI / verificación pre-commit |

**Estado v0.0.2:** `light` y `lint` operativos. `full` está stubbeado — el CLI exits con código 2. Aterriza con la integración LLM + Query real.

## Pipeline `full` (11 pasos)

1. **Load adapter.** Busca el Process adapter por `note_type` del frontmatter o inferencia desde dir/pattern (`applies_when`).
2. **Pre-process.** Extracción de texto (PDF, DOCX, etc.), parsing si es estructurado.
3. **Context injection.** Corre `context_injectors` declarados — cada uno hace una query al vault y se inyecta como variable en el prompt.
4. **Render prompt.** Sustituye `${placeholders}` en `prompt.md` con `note_body`, contexto inyectado, vocabulario de triples.
5. **LLM call.** Modelo declarado en `manifest.llm` (sonnet default; overrideable).
6. **Validate output.** Chequea contra `output_schema` (required fields presentes + types correctos) y `triple_vocabulary` (cada triple usa una relación declarada).
7. **Transform hook.** Si el manifest declara `transform_hook`, corre `transform.py` en sandbox con el output del LLM como input.
8. **Q&A check.** Si el LLM llamó `ask_user(...)` durante el processing (ej: materia ambigua) → crea una Q&A y deja el adapter en `awaiting_user_input`.
9. **Update indices.** `_index.md`, `_tags.md`, `_people.md` (si person resolver activo), promote concepts si superan threshold.
10. **File move.** A `destination_path` con frontmatter completo. Path siempre **relativo al vault**.
11. **Notify Output dispatcher.** Triggers `on_new(<note_type>)` para que Output adapters suscritos se enteren.

## Manifest schema

```yaml
adapter_name: <kebab-case>            # único; debe matchear el dir name
note_type: <snake_case>               # ej: apunte_clase

applies_when:
  source_dir: <relative-path>         # dir watched para auto-trigger
  matches_pattern: ["*.pdf", "*.md", "*.txt"]

llm: sonnet | haiku | opus            # default: sonnet
mode_default: full | light            # default: full

output_schema:
  required:
    <field>: <type>                   # type puede ser primitive o enum_dynamic
  optional:
    <field>: <type>

triple_vocabulary:                    # lista de relaciones permitidas
  - <relation>                        # ej: tema-de, expuesto-por, extiende

tag_axes:                             # ejes ortogonales de tags
  - axis: <name>
    format: "<axis>/<slug>"
    required: true | false
    min: <int>                        # mínimo de tags en este eje

destination_path: "<template>"        # ej: apuntes/{materia}/{fecha_clase}-{slug}.md
                                      # SIEMPRE relativo al vault — validador rechaza absolutos

qa_triggers:                          # cuándo disparar ask_user
  - name: <name>
    condition: "<expression>"

context_injectors:
  - name: <name>
    query: "<query-expression>"       # usado para inyectar contexto en el prompt

transform_hook: ./transform.py        # opcional, deferido en v0.0.2
```

## Validador del manifest

Bloquea install (errors) o loggea (warnings):

- **Errors:**
  - `destination_path` con path absoluto o path que se escapa via `..`
  - `triple_vocabulary` usa keywords reservados (`type`, `id`, `created`, `updated`, `tags`)
  - `tag_axes` con axes que overlapean entre sí
  - `qa_triggers[].condition` sintácticamente inválido
  - `context_injectors[].query` con expression mal formada
  - `output_schema.required` con field sin type
  - `transform_hook` declarado pero archivo no existe / no ejecutable
- **Warnings:**
  - Prompt sin referencias a `context_injectors` declarados (probable typo)
  - Sin `qa_triggers` (el LLM no tiene escape hatch a `ask_user`)

## Helpers usados internamente

- `parse_frontmatter(text)` — parser robusto (CRLF normalization, YAMLError handling).
- `extract_triples(frontmatter)` — extrae lista del campo `triples:`.
- `validate_against_vocabulary(triples, vocab)` — chequea cada `r` contra el vocabulario.
- `update_tag_index(vault, tag, note_slug)` — agrega al `_tags.md`.
- `append_to_log(vault, log_name, entry)` — append-only logs.
- `promote_concept(vault, concept, count)` — si un concepto aparece ≥ N veces, crea `conceptos/<slug>.md`.

## CLI

```bash
rufino process <note_path> --vault <X> --mode {light|full|lint} [--adapter-dir <PATH>]
```

- `--mode light` no requiere `--adapter-dir`; usa heurística para inferir dónde mover la nota.
- `--mode full` requiere `--adapter-dir` apuntando al Process adapter relevante. **Exits 2 en v0.0.2** (deferido).
- `--mode lint` valida sin modificar y sale con código 1 si hay errores.

## Ejemplo: adapter completo

Ver [`../writing-adapters.md#process-adapter`](../writing-adapters.md#process-adapter) — tiene manifest + prompt para el vertical facultad.

## Inmutabilidad

El `WorkerAdapterManifest` parseado está fully immutable (recursive `MappingProxyType` + tuplas). Si tu código intenta `manifest["new_field"] = "x"`, tira `TypeError`. Igual el `ProcessResult` — es `@dataclass(frozen=True)`.

Esto evita una clase entera de bugs donde un dispatcher mute state shared con un caller.

## Preservation policy

Si `update_tag_index()` o `append_to_log()` fallan **después** del LLM call exitoso, la nota source se preserva (no se `unlink()`-ea) — vas a poder retry sin perder el trabajo del LLM. Si todo OK, la source se elimina al final.

## Estado v0.0.2

- ✅ `mode_default: light` — operativo (registro + file move sin LLM)
- ✅ `mode_default: lint` — operativo (validación pure)
- ⏸ `mode_default: full` — engine implementado, CLI wiring deferido
- ⏸ `transform_hook` — manifest parsea, runner no invoca
- ✅ Q&A check (cuando `full` se cierre) — engine listo; espera `full` mode

## Referencia

- Shape "worker adapter": [`../adapters/worker-adapter.md`](../adapters/worker-adapter.md)
- Cómo escribir uno: [`../writing-adapters.md#process-adapter`](../writing-adapters.md#process-adapter)
