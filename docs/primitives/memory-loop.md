# Memory loop

Integración con conversaciones de Claude Code en curso. El usuario nunca invoca esto a mano — funciona transparente mientras conversa.

## Tres ramas

1. **Hooks** (`UserPromptSubmit`, `Stop`, `SessionStart`) instalados en `~/.claude/hooks/` — cargan reglas, detectan momentos para guardar.
2. **Skill `/remember`** — el mecanismo canónico de escritura al vault desde una conversación. Decide carpeta destino según `note_type`.
3. **Reglas globales** — markdown en `~/.claude/rules/common/<vertical>-*.md` que se cargan al iniciar cada sesión.

## Cuándo usar

Si el vertical involucra **gente conversando con Claude** sobre el dominio y querés capturar lo valioso sin que el usuario lo persista a mano. Casi todos los verticales se benefician — es el primitive más "ambiente" del framework.

## Adapter shape: vertical config

A diferencia de los Worker adapters (que ejecutan código), el Memory loop adapter es **declarativo + reglas para Claude**. No hay LLM call propio del framework; lo que hace es _configurar a Claude_ (el que está en la conversación).

```
~/.rufino/adapters/memory_loop/<adapter_name>/
├── manifest.yaml
└── rules/
    ├── <vertical>-vocabulary.md
    └── <vertical>-conventions.md
```

## Manifest schema

```yaml
adapter_name: <kebab-case>
vertical_name: <slug>                 # ej: facultad, finanzas, management

entity_types: [<type>, ...]           # ej: [apunte_clase, materia, profesor, paper, tp, examen]

note_destinations:
  <type>: "<path-template>"           # template con vars del frontmatter

rule_extensions:
  - ./rules/<vertical>-vocabulary.md
  - ./rules/<vertical>-conventions.md
```

## Validador del manifest

- **Errors:**
  - `vertical_name` no es kebab-case
  - `entity_types` vacío
  - `note_destinations` tiene un type que no está en `entity_types`
  - `note_destinations[type]` con path absoluto
  - `rule_extensions` apunta a archivo inexistente
  - `rule_extensions` con path que sale del adapter dir (path traversal)
- **Warnings:**
  - Sin `rule_extensions` (memory loop sin reglas = no le da contexto a Claude)
  - Heredoc marker collision si una regla contiene `RUFINO_RULES_EOF` en una línea sola (rare pero posible)

## Installer

`rufino install-memory-loop <adapter_dir> --vault X --claude-home Y` hace:

1. **Crear log de tx** en `<claude_home>/tx/install-memory-loop-<adapter_name>.json`
2. **Validar manifest** — si falla, abort con `InstallationError`
3. **Copiar reglas** a `~/.claude/rules/common/<vertical>-*.md` via `apply_and_log(tx_log, "write", ...)`
4. **Generar hook init** que carga las reglas + perfil + overview del vault al iniciar sesión
5. **Registrar en `~/.claude.json`** si hace falta (memory loop config refs)
6. Si todo OK → log conservado como auditoría
7. Si falla → `tx_log.rollback()` → todo lo escrito se borra (incluyendo hooks parcialmente instalados)

### Hardening del installer

Lecciones aprendidas (capturadas en code review de Plan 2):

- **Path traversal protegido** en `rule_extensions` — paths que escapan del adapter dir son rechazados antes de copiar.
- **Heredoc marker** del hook usa un marker único (`RUFINO_RULES_EOF`) — si una regla contiene esa string sola en una línea, el validador la rechaza.
- **`mkdir` rollback** usa `rmdir_if_empty` (no `shutil.rmtree`) — si en `~/.claude/hooks/` ya había hooks de Val pre-existentes, no se nukean.
- **CLI invoca `tx_log.rollback()` en `except InstallationError`** — no deja artefactos huérfanos.
- **Placeholders del hook template** se limpian del comment (sino `str.replace()` los expandía ahí también y el markdown se ejecutaba como bash). Smoke test valida `stderr == ""` al ejecutar el hook generado.

## Adapter ejemplo: facultad

`manifest.yaml`:

```yaml
adapter_name: memory-loop-facultad
vertical_name: facultad

entity_types: [apunte_clase, materia, profesor, paper, tp, examen]

note_destinations:
  apunte_clase: "apuntes/<materia>/<YYYY-MM-DD>-<slug>.md"
  paper: "papers/<materia>/<slug>.md"
  tp: "tps/<materia>/<YYYY-MM-DD>-<slug>.md"
  examen: "examenes/<materia>/<YYYY-MM-DD>-<tipo>.md"

rule_extensions:
  - ./rules/facultad-vocabulary.md
  - ./rules/facultad-conventions.md
```

`rules/facultad-vocabulary.md` (ejemplo):

```markdown
# Vocabulario del vertical facultad

## Tipos de entidad

- **apunte_clase** — nota de clase. Vive en `apuntes/<materia>/<YYYY-MM-DD>-<slug>.md`.
- **materia** — una materia de la carrera. Vive en `materias/<slug>.md`.
- **profesor** — persona que dicta. Vive en `profesores/<slug>.md`.
- **paper** — paper académico. Vive en `papers/<materia>/<slug>.md`.

## Triples canónicos

- `tema-de` — apunte tema-de materia
- `expuesto-por` — apunte expuesto-por profesor
- `dicta` — profesor dicta materia
- `referencia` — apunte/paper referencia paper

## Convenciones

- Si el usuario menciona un profesor que no existe, sugerí guardarlo como persona con tag `profesor/`.
- Si menciona una materia no registrada, preguntale si crearla.
- Notas de clase siempre van por materia, dentro por fecha-slug.
```

## Flujo típico

```
1. Usuario abre Claude Code en ~/facultad/
       ↓
2. Hook init (SessionStart) carga:
       ├─→ perfil.md del vault
       ├─→ ~/.claude/rules/common/facultad-vocabulary.md
       ├─→ ~/.claude/rules/common/facultad-conventions.md
       └─→ overview del proyecto (detectado por CWD)
       ↓
3. Usuario: "el profe Méndez dio una clase sobre redes bayesianas"
       ↓
4. Claude (siguiendo las reglas):
       ├─→ detecta nueva mención de [[profesor-mendez]] (no existe)
       ├─→ detecta concepto regresion-bayesiana
       ├─→ propone guardar via /remember
       │       ├─→ escribe apuntes/<materia>/<fecha>-clase-redes-bayesianas.md
       │       └─→ crea profesores/mendez.md con triple dicta → <materia>
       │
5. Hook stop (al cierre de sesión) pregunta si hay más para guardar
```

## Versionado

Las reglas de un memory loop adapter se cargan al iniciar **cada** sesión de Claude Code dentro del vault. Si modificás `rules/<vertical>-*.md`:

- Al próximo arranque de Claude Code, las reglas actualizadas se cargan (no requiere reinstall).
- Si la modificación es **breaking** (cambia entity_types, etc.), reinstalar el adapter es lo limpio: `rufino install-memory-loop <adapter_dir> --vault X --claude-home Y` es idempotente.

## Estado v0.0.2

- ✅ Installer transaccional con rollback completo
- ✅ Validador de manifest con path traversal protegido
- ✅ Hook init + skill /remember + reglas en `~/.claude/rules/common/`
- ⚠ Hook stop (al cierre) — esqueleto generado pero la integración con el resto del framework (preguntar al usuario qué guardar) depende del Process pipeline en modo full

## Referencia

- Shape "vertical config": [`../adapters/vertical-config.md`](../adapters/vertical-config.md)
- Cómo escribir uno: [`../writing-adapters.md#memory-loop-adapter`](../writing-adapters.md#memory-loop-adapter)
