# rufino-notes-and-memory — Design Spec

**Fecha:** 2026-05-13
**Estado:** Diseño aprobado, pendiente de implementación.

## Propósito

Empaquetar el sistema personal de memoria y procesamiento de notas de Val en un repo standalone que cualquier persona pueda clonar y dejar funcionando con su propio vault de Obsidian. Las piezas viven hoy dispersas entre `~/.claude/`, el repo `claudeSetup` y el vault `vaultlentino`; este repo las extrae y las consolida.

## Alcance

**Incluye:**
- **Sistema de memoria genérico (obsidian-memory)**: regla, hook de recordatorio al cerrar conversaciones, skill `/remember` para escritura canónica al vault.
- **Sistema Rufino**: 6 prompts, 5 scripts cron, regla, vault skeleton de `rufino/`.
- **Skeleton de vault completo**: estructura mínima funcional para un usuario que arranca de cero — `rufino/`, `conceptos/`, `proyectos/`, `sesiones/`, `_meta/`, `_templates/`, `obsidian-config/`, `seed-notes/`, `perfil.md`, `preferencias.md`.
- **Launchd plists** (macOS) para los 3 crons de Rufino.

**No incluye:**
- App `Rufino` (dashboard, rufino-mac, rufino-windows). Esos viven en sus propios repos.
- Auto-memory de Claude (`~/.claude/projects/.../memory/`).
- Auto-backup horario del vault (lo hace el plugin Obsidian-Git instalado adentro de Obsidian; el README lo menciona como prerrequisito).
- Cualquier "memoria del mempalace" o sistema externo.

## Audiencia y plataforma

- Usuarios técnicos cómodos editando archivos shell y plists.
- macOS / Linux con bash. No Windows.
- Asume Claude Code, Obsidian, `jq` instalados (el README los lista).

## Estrategia de instalación

**Manual paso a paso por README.** Sin script de install. Razones:
- Volumen chico de archivos; un README guía bien.
- Más fácil de auditar y entender lo que se está cambiando en `~/.claude/` y el vault.
- Menos código que mantener.

**Configuración vía variables de entorno**, no archivos editables ni `config.sh`. Las env vars relevantes:

| Env var | Default | Para qué |
|---|---|---|
| `RUFINO_VAULT_PATH` | (sin default — el script falla si no está) | Path absoluto al vault de Obsidian |
| `RUFINO_DISPLAY_NAME` | `"el usuario"` | Cómo Claude se refiere al usuario |
| `RUFINO_LOG_DIR` | `$HOME/.claude/logs/rufino` | Dónde escribir logs de los crons |

Excepciones (no aceptan env var, hay que editar a mano):
- **Plists**: `ProgramArguments`, `StandardOutPath`, `StandardErrorPath`, y el valor de `RUFINO_VAULT_PATH` adentro de `EnvironmentVariables`. No hay shell expansion en plists.
- **Reglas (`obsidian-memory.md`, `rufino.md`)**: se cargan como contexto plano para Claude. El README dice "abrilas y reemplazá `$VAULT_PATH` y `$DISPLAY_NAME` con tus valores reales".

## Estructura del repo

```
rufino-notes-and-memory/
├── README.md
├── .gitignore
│
├── claude/                                  # → ~/.claude/
│   ├── hooks/
│   │   └── obsidianMemoryCheck.sh
│   ├── prompts/
│   │   ├── rufino-daily.md
│   │   ├── rufino-light-cron.md
│   │   ├── rufino-import-plan.md
│   │   ├── rufino-process-single.md
│   │   ├── rufino-reprocess.md
│   │   └── rufino-lint.md
│   ├── rules/
│   │   └── common/
│   │       ├── obsidian-memory.md
│   │       └── rufino.md
│   ├── scripts/
│   │   ├── rufino-cron.sh
│   │   ├── rufino-light-cron.sh
│   │   ├── rufino-import-plan.sh
│   │   ├── rufino-process-single.sh
│   │   └── rufino-lint-cron.sh
│   └── commands/
│       └── remember.md                      # skill /remember
│
├── vault-skeleton/                          # → adentro del vault de Obsidian
│   ├── perfil.md                            # template vacío — quién es el usuario
│   ├── preferencias.md                      # template vacío — preferencias de trabajo
│   ├── rufino/
│   │   ├── _index.md
│   │   ├── _pendientes.md
│   │   ├── _people.md
│   │   ├── _processing-log.md
│   │   ├── _tags.md
│   │   ├── _archive/.gitkeep
│   │   └── _people/.gitkeep
│   ├── conceptos/.gitkeep                   # lo llena el cron light-cron
│   ├── proyectos/.gitkeep                   # lo llena Claude vía regla
│   ├── sesiones/.gitkeep                    # lo llena la skill /remember
│   ├── _meta/
│   │   ├── relationship-vocab.md            # vocabulario canónico de triples
│   │   ├── projectPaths.md
│   │   ├── design.md
│   │   ├── implementationPlan.md
│   │   ├── log.md
│   │   └── setup-for-others.md
│   ├── _templates/
│   ├── obsidian-config/
│   └── seed-notes/
│
└── system/
    └── launchd/                             # → ~/Library/LaunchAgents/
        ├── com.user.rufino-cron.plist
        ├── com.user.rufino-light-cron.plist
        └── com.user.rufino-lint-cron.plist
```

## Cómo se llenan las carpetas que arrancan vacías

| Carpeta | Cuándo se llena | Por qué componente |
|---|---|---|
| `conceptos/` | Cuando un concepto aparece en ≥2 notas | Cron `rufino-light-cron` (concept promotion) |
| `proyectos/<x>/overview.md` | Cuando el usuario abre Claude en un CWD nuevo | Regla `obsidian-memory.md` instruye a Claude a crearlo |
| `sesiones/<YYYY-MM-DD-tema>.md` | Cuando el usuario pide "guardá esto como sesión" | Skill `/remember` decide la carpeta destino |
| `rufino/<project>/<type>/` | Cuando se procesa una nota cruda de `rufino/*.md` | Cron `rufino-cron` |
| `_people/<persona>.md` | Cuando se detecta una persona nueva | Cron `rufino-cron` |

## Cambios a archivos originales

**Scripts (`claude/scripts/rufino-*.sh`):**
- Eliminar placeholders literales `__VAULT_PATH__`, `__DISPLAY_NAME__`.
- Todos los paths salen de env vars: `RUFINO_VAULT_PATH`, `RUFINO_DISPLAY_NAME`, `RUFINO_LOG_DIR`.
- Eliminar paths absolutos al dashboard (los scripts NO deben asumir que `rufino-dashboard/` existe).
- Detección de `claude` binario: `CLAUDE=$(command -v claude || echo $HOME/.local/bin/claude)`.
- Check explícito al inicio: si `RUFINO_VAULT_PATH` no está seteada, salir con mensaje claro.
- Mantener `set -euo pipefail` y locking con stale-lock detection.

**Prompts (`claude/prompts/rufino-*.md`):**
- Reemplazar `__VAULT_PATH__` y `__DISPLAY_NAME__` por `${RUFINO_VAULT_PATH}` y `${RUFINO_DISPLAY_NAME}`.
- Los scripts wrapper aplican `envsubst` antes de pasar el prompt a `claude -p`. El usuario no edita prompts.

**Reglas (`claude/rules/common/{obsidian-memory,rufino}.md`):**
- Mantener `$VAULT_PATH` y `$DISPLAY_NAME` como tokens visibles a reemplazar.
- README incluye un paso explícito: "abrí estas dos reglas y reemplazá `$VAULT_PATH` con tu path real y `$DISPLAY_NAME` con tu nombre".

**Hook (`claude/hooks/obsidianMemoryCheck.sh`):**
- Ya es portable (solo usa `$SESSION_ID` que viene del stdin de Claude). No requiere cambios.

**Plists (`system/launchd/com.user.rufino-*.plist`):** cambios en cada uno de los 3 plists:
- `Label`: `com.val.rufino-*` → `com.user.rufino-*`.
- `ProgramArguments[1]` (path al .sh): hoy `/Users/val/.claude/scripts/rufino-*.sh` → en el repo viene como `__HOME__/.claude/scripts/rufino-*.sh`. El usuario reemplaza `__HOME__` con su `$HOME` real (launchd no expande env vars en este field).
- `StandardOutPath`: hoy `/Users/val/Files/codeProjects/Rufino/rufino-dashboard/logs/rufino-*.log` → en el repo `__HOME__/.claude/logs/rufino/rufino-*.log`. Mismo reemplazo de `__HOME__`.
- `StandardErrorPath`: ídem.
- `EnvironmentVariables.RUFINO_VAULT_PATH`: en el repo viene como string vacío `""`. El usuario llena con su path absoluto al vault.
- El README incluye un snippet con `sed -i ''` que hace los 4 reemplazos en bloque sobre los 3 plists. **Excepción al "env vars máximas"**: como launchd no expande env vars en `ProgramArguments` ni paths de logs, en este único punto usamos placeholder `__HOME__` + sed. Es el lugar más barato para hacer la concesión.

**Commands (`claude/commands/remember.md`):**
- Mismo tratamiento que reglas — `$VAULT_PATH` y `$DISPLAY_NAME` como tokens, el README pide reemplazar.

## Estructura del README

Secciones del README en orden:

1. **Título + tagline** de una línea.
2. **Cómo funciona (de un vistazo)**: 4-5 bullets explicando las dos capas (obsidian-memory + rufino), los 3 crons, el hook, la skill.
3. **Prerrequisitos**: macOS/Linux, bash, Claude Code, Obsidian, `obsidian-git`, `jq`.
4. **Instalación paso a paso**:
   - 4.1. Clonar.
   - 4.2. Setear env vars en `~/.zshenv`.
   - 4.3. Copiar `claude/` a `~/.claude/` con `cp -rn` (no-clobber).
   - 4.4. Editar reglas: reemplazar `$VAULT_PATH` y `$DISPLAY_NAME`.
   - 4.5. Copiar `vault-skeleton/` al vault con `cp -rn`. **Completar `perfil.md` y `preferencias.md` antes de empezar.**
   - 4.6. Editar los 3 plists (paths absolutos + env var del vault).
   - 4.7. `launchctl load` los 3.
5. **Verificación**: 4 chequeos concretos (ver siguiente sección).
6. **Estructura del repo** (árbol).
7. **Qué hace cada cron**:
   - `rufino-cron` (22:00): procesa inbox raíz + catch-up.
   - `rufino-light-cron` (02:00): triples + concept promotion en notas escritas a mano.
   - `rufino-lint-cron` (03:00): valida invariantes del vault.
8. **Qué hace cada componente** (hook, skill, reglas).
9. **Troubleshooting**: 3-4 problemas comunes (cron no corre, reglas no se aplican, /remember falla).
10. **Mantenimiento**: cómo upgradear (git pull + repetir copies), cómo contribuir cambios upstream.
11. **Cómo desinstalar**: `launchctl unload` + `rm` de los archivos.

## Verificación post-install (el README cierra con esto)

1. `launchctl list | grep rufino` → ver `com.user.rufino-cron`, `com.user.rufino-light-cron`, `com.user.rufino-lint-cron`.
2. Crear `$RUFINO_VAULT_PATH/rufino/test.md` con texto cualquiera. Correr `bash ~/.claude/scripts/rufino-cron.sh`. Verificar que `$RUFINO_LOG_DIR/rufino-cron.log` muestra procesamiento exitoso y la nota se movió a `rufino/<proyecto>/<tipo>/`.
3. Abrir Claude Code en un directorio nuevo. Pedir cualquier tarea. Confirmar que se creó `$RUFINO_VAULT_PATH/proyectos/<x>/overview.md` y que `$RUFINO_VAULT_PATH/_meta/projectPaths.md` se actualizó.
4. Pedirle a Claude "guardá esta conversación como sesión" → confirmar que la skill `/remember` creó `$RUFINO_VAULT_PATH/sesiones/<YYYY-MM-DD-tema>.md`.

## Edge cases

- **`~/.claude/` pre-existente con archivos del usuario**: `cp -rn` no sobrescribe. Si hay conflicto, queda al usuario decidir si reemplaza. El README lo advierte.
- **Vault pre-existente con archivos**: igual con `cp -rn`. Si `perfil.md` ya existe, no se pisa.
- **`claude` no en `$PATH`**: los scripts usan `command -v claude || $HOME/.local/bin/claude`.
- **Env vars no seteadas**: scripts fallan rápido al inicio con error claro (`"RUFINO_VAULT_PATH must be set"`).
- **`jq` falta**: el hook falla. Listed en prerrequisitos.
- **Linux sin launchd**: v1 incluye solo plists de launchd (macOS). En Linux el usuario tiene que armar sus propias entradas (cron / systemd unit) apuntando a los mismos scripts `$HOME/.claude/scripts/rufino-*.sh`. El README incluye un ejemplo mínimo de crontab equivalente a los 3 plists, pero no archivos systemd.

## Mantenimiento

- No hay sync automático entre el repo y `~/.claude/` o el vault. Source of truth post-install es lo que está instalado en la máquina.
- Para upgrades: `git pull` + repetir los pasos relevantes del README (copy + `launchctl unload && load`).
- Sin tests automatizados. La verificación de 4 pasos del README es la prueba.

## Decisiones clave

| Decisión | Razón |
|---|---|
| Espejo del filesystem destino (`claude/`, `vault-skeleton/`, `system/launchd/`) | Install manual + README → mientras más se parezca el repo al destino, menos fricción. |
| Sin script de install | Volumen chico, más auditable, menos mantenimiento. |
| Env vars máximas | Una sola fuente de config, el usuario no edita scripts. |
| Plists con placeholder `__HOME__` + sed (única excepción a "env vars máximas") | Launchd no expande env vars en `ProgramArguments` ni paths de logs. El sed en el README es un comando único de 1 línea. Más simple que un install script entero para esto solo. |
| Skeleton "vault completo inicial" | Plug-and-play para quien arranca de cero. Si ya tiene vault, `cp -rn` no pisa. |
| Solo macOS/Linux | Val no usa Windows. Espejar claudeSetup en PowerShell duplica mantenimiento sin retorno. |
| Incluir `/remember` y `obsidian-memory` (no solo Rufino) | Sin la capa de memoria, Rufino es huérfano. El nombre `rufino-notes-and-memory` lo refleja. |
| Sin auto-memory (`~/.claude/projects/.../memory/`) | Es otro sistema (Anthropic-managed), no toca el vault de Obsidian. |
| Sin auto-backup vault | Lo hace el plugin `obsidian-git` adentro de Obsidian. README lo menciona como prerrequisito. |

## Out of scope (para evitar scope creep en implementación)

- Soporte Windows.
- Script de install.
- Tests automatizados.
- Sync bidireccional entre repo e instalado.
- Sistema auto-memory de Claude.
- Cualquier app gráfica (dashboard).
- Integración con sistemas externos (mempalace, etc.).
- Soporte multi-vault (un usuario, un vault).

## Próximo paso

Crear plan de implementación (skill `writing-plans`) que defina:
- Orden de creación de archivos.
- Cómo transformar cada archivo origen al de destino (qué `sed`/`envsubst` aplicar).
- Estructura del README con contenido concreto (no solo outline).
- Commit strategy (¿un commit final o por capa?).
