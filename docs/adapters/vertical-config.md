# Vertical config adapter

Shape de adapter usado por: **Memory loop**.

A diferencia de los Worker adapters (que ejecutan código), el Vertical config es **declarativo + reglas para Claude**. No hay LLM call propio del adapter; lo que hace es _configurar a Claude_ en sus conversaciones dentro del vault.

## Estructura

```
~/.rufino/adapters/memory_loop/<adapter_name>/
├── manifest.yaml
└── rules/
    ├── <vertical>-vocabulary.md
    └── <vertical>-conventions.md
```

`adapter_name` es kebab-case y matchea el dir name.

## Manifest

```yaml
adapter_name: <kebab-case>
vertical_name: <slug>                 # ej: facultad, finanzas, management

entity_types: [<type>, ...]           # ej: [apunte_clase, materia, profesor]

note_destinations:
  <type>: "<path-template>"           # template con vars del frontmatter
                                      # ej: apunte_clase: "apuntes/<materia>/<YYYY-MM-DD>-<slug>.md"

rule_extensions:
  - ./rules/<vertical>-vocabulary.md
  - ./rules/<vertical>-conventions.md
```

### Campos

| Campo | Required | Notas |
|---|---|---|
| `adapter_name` | sí | kebab-case, único, matchea dir name |
| `vertical_name` | sí | slug del vertical (ej: `facultad`) — se usa para nombrar las reglas instaladas (`~/.claude/rules/common/<vertical>-*.md`) |
| `entity_types` | sí | lista de tipos de notas que tu vertical maneja; cada uno tiene que aparecer en `note_destinations` |
| `note_destinations` | sí | mapeo entity_type → path template. Path siempre **relativo al vault**. Variables permitidas: cualquier frontmatter field (`<materia>`, `<fecha>`, `<slug>`, etc.) + `<YYYY-MM-DD>` |
| `rule_extensions` | sí | lista de paths a `.md` files relativos al adapter dir. Cada uno se copia a `~/.claude/rules/common/<vertical>-<basename>.md` al instalar |

## Las reglas

Cada archivo `.md` declarado en `rule_extensions` se copia a `~/.claude/rules/common/` con prefijo `<vertical>-`. Claude los carga al iniciar **cada sesión**.

Convenciones:

- **`<vertical>-vocabulary.md`** — define entidades, tipos, triples canónicos, tag axes.
- **`<vertical>-conventions.md`** — cuándo crear qué tipo de nota, cuándo sugerir guardar, cómo nombrar slugs.

### Ejemplo: `facultad-vocabulary.md`

```markdown
# Vocabulario del vertical facultad

## Tipos de entidad

- **apunte_clase** — nota de clase. Vive en `apuntes/<materia>/<YYYY-MM-DD>-<slug>.md`.
- **materia** — materia de la carrera. Vive en `materias/<slug>.md`.
- **profesor** — persona que dicta. Vive en `profesores/<slug>.md`.

## Triples canónicos

- `tema-de` — apunte tema-de materia
- `expuesto-por` — apunte expuesto-por profesor
- `dicta` — profesor dicta materia
```

### Ejemplo: `facultad-conventions.md`

```markdown
# Convenciones del vertical facultad

## Cuándo crear apunte_clase

Cuando el usuario describe contenido de una clase (tópicos, ejercicios, dudas).
**No** cuando solo nombra una materia sin detalle.

## Cuándo crear materia

Cuando el usuario menciona una materia que no existe en `materias/`. Preguntá antes.

## Cuándo crear profesor

Cuando se menciona el nombre de un profesor nuevo. Sugerí guardarlo como persona
con tag `profesor/` y triple `dicta → <materia>`.

## Naming

- Slugs en kebab-case lowercase.
- Materias: nombre corto canónico (`ml-i`, no `machine-learning-i-cursada-2026`).
- Fechas: `YYYY-MM-DD`.
```

## Validador del manifest

- **Errors:**
  - `vertical_name` no es kebab-case
  - `entity_types` vacío
  - `note_destinations` tiene un type que no está en `entity_types`
  - `note_destinations[type]` con path absoluto o con `..` que escapa
  - `rule_extensions` apunta a archivo inexistente
  - `rule_extensions` con path que sale del adapter dir (path traversal)
- **Warnings:**
  - Sin `rule_extensions` (memory loop sin reglas = no le da contexto a Claude)

## Installer

`rufino install-memory-loop <adapter_dir> --vault X --claude-home Y` ejecuta:

1. Validar manifest. Si falla → `InstallationError`.
2. Para cada archivo en `rule_extensions`:
   - Copiar a `<claude_home>/rules/common/<vertical>-<basename>.md`
   - Registrar en `tx_log` con `apply_and_log(op="write", rollback="delete")`
3. Generar hook init (`SessionStart`) que carga las reglas + perfil + overview del vault.
   - Registrar en `tx_log`.
4. Si todo OK → log conservado como auditoría.
5. Si falla → `tx_log.rollback()` → todo lo escrito se borra.

Idempotente: re-correr no causa side effects.

## Hot reload

Si modificás un archivo en `rules/` después del install:

- Al próximo arranque de Claude Code dentro del vault, las reglas actualizadas se cargan automáticamente (no requiere reinstall).
- Si la modificación es **breaking** (cambia entity_types, etc.), reinstalar el adapter es lo limpio — el installer es idempotente.

## Por qué es shape distinto

Forzar al memory loop a ser un Worker adapter (con prompt.md / template.md / transform.py) sería ceremonia inútil — la lógica del memory loop **vive en Claude**, no en código del framework. El adapter solo necesita:

- Declarar qué entidades hay (estructura)
- Decir dónde van las notas (path templates)
- Pasar reglas a Claude (markdown plano)

Worker adapter habría agregado boilerplate que no sirve para nada.

## Referencia

- Primitive: [`../primitives/memory-loop.md`](../primitives/memory-loop.md)
- Cómo escribir uno: [`../writing-adapters.md#memory-loop-adapter`](../writing-adapters.md#memory-loop-adapter)
