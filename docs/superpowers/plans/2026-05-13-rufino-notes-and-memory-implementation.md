# rufino-notes-and-memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir el repo standalone `rufino-notes-and-memory` que empaqueta el sistema de memoria + Rufino para que cualquier persona pueda clonarlo e instalarlo manualmente vía README.

**Architecture:** Espejo del filesystem destino: `claude/` → `~/.claude/`, `vault-skeleton/` → vault de Obsidian, `system/launchd/` → `~/Library/LaunchAgents/`. Sin script de install, configuración por env vars, plists con placeholder `__HOME__` + sed.

**Tech Stack:** Bash, Markdown, launchd (plists XML), envsubst para reemplazos en runtime.

**Source of truth for files:** `/Users/val/Files/codeProjects/claudeSetup/` (scripts, prompts, reglas, hook, skeleton) y `~/Library/LaunchAgents/com.val.rufino-*.plist` (plists).

**Repo destination:** `/Users/val/Files/rufino/`.

**Spec:** Ver `docs/superpowers/specs/2026-05-13-rufino-notes-and-memory-design.md`.

---

## File Structure

```
rufino-notes-and-memory/
├── README.md                                           # Task 10
├── .gitignore                                          # Task 1
├── claude/
│   ├── hooks/obsidianMemoryCheck.sh                    # Task 6
│   ├── prompts/rufino-{daily,light-cron,import-plan,process-single,reprocess,lint}.md  # Task 4
│   ├── rules/common/{obsidian-memory,rufino}.md        # Task 5
│   ├── scripts/rufino-{cron,light-cron,import-plan,process-single,lint-cron}.sh  # Task 3
│   └── commands/remember.md                            # Task 7
├── vault-skeleton/                                     # Task 8 (todo)
└── system/launchd/com.user.rufino-{cron,light-cron,lint-cron}.plist  # Task 9
```

**Nota:** `rufino-import-plan.sh` y `rufino-process-single.sh` NO tienen plist asociado porque NO son cron — son on-demand (los dispara el dashboard de Val, que NO está incluido en este repo). Quedan disponibles como scripts ejecutables manualmente.

---

## Patrones de transformación reutilizables

**Para scripts (`claude/scripts/rufino-*.sh`):** aplicar este sed sobre cada archivo original:

```bash
sed -E \
  -e 's|VAULT_PATH="\$\{RUFINO_VAULT_PATH:-__VAULT_PATH__\}"|VAULT_PATH="${RUFINO_VAULT_PATH:?RUFINO_VAULT_PATH must be set}"|g' \
  -e 's|\*\)  ABS_TARGET="\$\{RUFINO_VAULT_PATH:-__VAULT_PATH__\}/\$TARGET" \;\;|*)  ABS_TARGET="${RUFINO_VAULT_PATH:?RUFINO_VAULT_PATH must be set}/$TARGET" ;;|g' \
  -e 's|CLAUDE="\$HOME/\.local/bin/claude"|CLAUDE="$(command -v claude || echo "$HOME/.local/bin/claude")"|g' \
  -e 's|LOGFILE="\$HOME/Files/codeProjects/rufino-dashboard/logs/(rufino-[a-z-]+)\.log"|LOGFILE="${RUFINO_LOG_DIR:-$HOME/.claude/logs/rufino}/\1.log"|g' \
  -e 's|__DISPLAY_NAME__|the user|g' \
  < SRC > DEST
```

Adicionalmente, los scripts que `cat` el prompt deben pasarlo por `envsubst` para que `${RUFINO_VAULT_PATH}` y `${RUFINO_DISPLAY_NAME}` se expandan. Línea a cambiar: `PROMPT=$(cat "$PROMPT_FILE")` → `PROMPT=$(envsubst '${RUFINO_VAULT_PATH} ${RUFINO_DISPLAY_NAME}' < "$PROMPT_FILE")`. Esto se hace por edición explícita (no por sed) porque puede aparecer en distinto lugar según script.

**Para prompts (`claude/prompts/rufino-*.md`):** aplicar este sed:

```bash
sed -E \
  -e 's|__VAULT_PATH__|${RUFINO_VAULT_PATH}|g' \
  -e 's|__DISPLAY_NAME__|${RUFINO_DISPLAY_NAME}|g' \
  -e 's|__INBOX_FILE__|${INBOX_FILE}|g' \
  -e 's|__PLAN_FILE__|${PLAN_FILE}|g' \
  -e 's|__TARGET__|${TARGET}|g' \
  < SRC > DEST
```

(Los placeholders extra como `__INBOX_FILE__` solo aparecen en `rufino-import-plan.md` y `rufino-process-single.md`. Si no están en un prompt, sed no hace nada.)

**Para reglas y skill (`claude/rules/common/*.md`, `claude/commands/remember.md`):** aplicar este sed:

```bash
sed -E \
  -e 's|__VAULT_PATH__|$VAULT_PATH|g' \
  -e 's|__DISPLAY_NAME__|$DISPLAY_NAME|g' \
  -e 's|/Users/val/Files/vaultlentino|$VAULT_PATH|g' \
  < SRC > DEST
```

(Las reglas se cargan como contexto plano por Claude; los tokens `$VAULT_PATH` y `$DISPLAY_NAME` quedan visibles para que el usuario los reemplace con su path/nombre antes de instalar.)

**Para plists (`system/launchd/com.user.rufino-*.plist`):** aplicar este sed sobre los originales de `~/Library/LaunchAgents/`:

```bash
sed -E \
  -e 's|<string>com\.val\.(rufino-[a-z-]+)</string>|<string>com.user.\1</string>|g' \
  -e 's|/Users/val/\.claude/scripts/|__HOME__/.claude/scripts/|g' \
  -e 's|/Users/val/Files/codeProjects/Rufino/rufino-dashboard/logs/|__HOME__/.claude/logs/rufino/|g' \
  -e 's|<string>/Users/val/Files/vaultlentino</string>|<string></string>|g' \
  < SRC > DEST
```

---

## Task 1: Setup repo (.gitignore + estructura mínima)

**Files:**
- Create: `/Users/val/Files/rufino/.gitignore`

- [ ] **Step 1: Verificar que el repo ya está iniciado**

Run: `cd ~/Files/rufino && git log --oneline`
Expected: muestra el commit del spec (`164ad72 docs: initial design spec...`).

- [ ] **Step 2: Crear `.gitignore`**

Write `/Users/val/Files/rufino/.gitignore`:
```
.DS_Store
*.swp
*.swo
*~
logs/
.processing.lock
.light-cron.lock
```

- [ ] **Step 3: Commit**

```bash
cd ~/Files/rufino
git add .gitignore
git commit -m "chore: add gitignore"
```

---

## Task 2: Crear estructura de directorios

**Files:**
- Create: `claude/{hooks,prompts,rules/common,scripts,commands}/`, `vault-skeleton/`, `system/launchd/`.

- [ ] **Step 1: Crear todas las carpetas**

```bash
cd ~/Files/rufino
mkdir -p claude/hooks claude/prompts claude/rules/common claude/scripts claude/commands
mkdir -p vault-skeleton
mkdir -p system/launchd
```

- [ ] **Step 2: Verificar**

Run: `find ~/Files/rufino -type d -not -path '*/\.*' | sort`
Expected (en orden):
```
/Users/val/Files/rufino
/Users/val/Files/rufino/claude
/Users/val/Files/rufino/claude/commands
/Users/val/Files/rufino/claude/hooks
/Users/val/Files/rufino/claude/prompts
/Users/val/Files/rufino/claude/rules
/Users/val/Files/rufino/claude/rules/common
/Users/val/Files/rufino/claude/scripts
/Users/val/Files/rufino/docs
/Users/val/Files/rufino/docs/superpowers
/Users/val/Files/rufino/docs/superpowers/plans
/Users/val/Files/rufino/docs/superpowers/specs
/Users/val/Files/rufino/system
/Users/val/Files/rufino/system/launchd
/Users/val/Files/rufino/vault-skeleton
```

- [ ] **Step 3: No commit todavía** — git no trackea directorios vacíos. El próximo task agrega archivos y commitea.

---

## Task 3: Copiar y transformar scripts (claude/scripts/)

**Files:**
- Create: `claude/scripts/rufino-{cron,light-cron,import-plan,process-single,lint-cron}.sh`
- Source: `/Users/val/Files/codeProjects/claudeSetup/claude-config/scripts/rufino-*.sh`

- [ ] **Step 1: Copiar y transformar los 5 scripts con sed**

```bash
cd ~/Files/rufino
SRC=/Users/val/Files/codeProjects/claudeSetup/claude-config/scripts

for f in rufino-cron rufino-light-cron rufino-import-plan rufino-process-single rufino-lint-cron; do
  sed -E \
    -e 's|VAULT_PATH="\$\{RUFINO_VAULT_PATH:-__VAULT_PATH__\}"|VAULT_PATH="${RUFINO_VAULT_PATH:?RUFINO_VAULT_PATH must be set}"|g' \
    -e 's|ABS_TARGET="\$\{RUFINO_VAULT_PATH:-__VAULT_PATH__\}/\$TARGET"|ABS_TARGET="${RUFINO_VAULT_PATH:?RUFINO_VAULT_PATH must be set}/$TARGET"|g' \
    -e 's|CLAUDE="\$HOME/\.local/bin/claude"|CLAUDE="$(command -v claude || echo "$HOME/.local/bin/claude")"|g' \
    -e 's|LOGFILE="\$HOME/Files/codeProjects/rufino-dashboard/logs/(rufino-[a-z-]+)\.log"|LOGFILE="${RUFINO_LOG_DIR:-$HOME/.claude/logs/rufino}/\1.log"|g' \
    -e 's|__DISPLAY_NAME__|the user|g' \
    "$SRC/$f.sh" > "claude/scripts/$f.sh"
  chmod +x "claude/scripts/$f.sh"
done
```

- [ ] **Step 2: Aplicar envsubst en los scripts que cargan prompts**

Tres scripts cargan prompts con `cat`: `rufino-cron.sh`, `rufino-light-cron.sh`, `rufino-lint-cron.sh`. Reemplazar la línea `PROMPT=$(cat "$PROMPT_FILE")` por `PROMPT=$(envsubst '${RUFINO_VAULT_PATH} ${RUFINO_DISPLAY_NAME}' < "$PROMPT_FILE")` en los tres.

```bash
cd ~/Files/rufino
for f in claude/scripts/rufino-cron.sh claude/scripts/rufino-light-cron.sh claude/scripts/rufino-lint-cron.sh; do
  sed -i '' 's|PROMPT=\$(cat "\$PROMPT_FILE")|PROMPT=$(envsubst '"'"'${RUFINO_VAULT_PATH} ${RUFINO_DISPLAY_NAME}'"'"' < "$PROMPT_FILE")|g' "$f"
done
```

Los scripts `rufino-import-plan.sh` y `rufino-process-single.sh` construyen el prompt con variables propias (`INBOX_FILE`, `PLAN_FILE`, `TARGET`). Después de aplicar el primer sed del Step 1, verificar que la línea que carga el prompt incluya `envsubst` con las variables correspondientes. Si aún tienen `cat "$PROMPT_FILE"` plano, hay que cambiarla a:

```bash
# para rufino-import-plan.sh:
PROMPT=$(envsubst '${RUFINO_VAULT_PATH} ${RUFINO_DISPLAY_NAME} ${INBOX_FILE} ${PLAN_FILE}' < "$PROMPT_FILE")

# para rufino-process-single.sh:
PROMPT=$(envsubst '${RUFINO_VAULT_PATH} ${RUFINO_DISPLAY_NAME} ${TARGET}' < "$PROMPT_FILE")
```

Aplicar manualmente con Edit en cada uno si hace falta. (Si los scripts originales ya construyen el prompt de otra forma — por ejemplo, sustituyendo placeholders con `sed` antes de cada llamada a `claude -p` —, mantener esa lógica pero cambiar los placeholders de `__VAR__` a `${VAR}` para que envsubst funcione.)

- [ ] **Step 3: Verificar sintaxis con bash -n**

```bash
cd ~/Files/rufino
for f in claude/scripts/*.sh; do
  bash -n "$f" && echo "$f OK" || echo "$f FAILED"
done
```
Expected: 5 líneas con `OK`.

- [ ] **Step 4: Verificar que no quedaron placeholders crudos**

```bash
cd ~/Files/rufino
grep -n -E "__VAULT_PATH__|__DISPLAY_NAME__|rufino-dashboard" claude/scripts/*.sh && echo "FOUND PLACEHOLDERS" || echo "clean"
```
Expected: `clean`.

- [ ] **Step 5: Commit**

```bash
cd ~/Files/rufino
git add claude/scripts/
git commit -m "feat: add rufino scripts (transformed from claudeSetup)"
```

---

## Task 4: Copiar y transformar prompts (claude/prompts/)

**Files:**
- Create: `claude/prompts/rufino-{daily,light-cron,import-plan,process-single,reprocess,lint}.md`
- Source: `/Users/val/Files/codeProjects/claudeSetup/claude-config/prompts/rufino-*.md`

- [ ] **Step 1: Copiar y transformar los 6 prompts con sed**

```bash
cd ~/Files/rufino
SRC=/Users/val/Files/codeProjects/claudeSetup/claude-config/prompts

for f in rufino-daily rufino-light-cron rufino-import-plan rufino-process-single rufino-reprocess rufino-lint; do
  sed -E \
    -e 's|__VAULT_PATH__|${RUFINO_VAULT_PATH}|g' \
    -e 's|__DISPLAY_NAME__|${RUFINO_DISPLAY_NAME}|g' \
    -e 's|__INBOX_FILE__|${INBOX_FILE}|g' \
    -e 's|__PLAN_FILE__|${PLAN_FILE}|g' \
    -e 's|__TARGET__|${TARGET}|g' \
    "$SRC/$f.md" > "claude/prompts/$f.md"
done
```

- [ ] **Step 2: Verificar que no quedaron placeholders crudos**

```bash
cd ~/Files/rufino
grep -n -E "__VAULT_PATH__|__DISPLAY_NAME__|__INBOX_FILE__|__PLAN_FILE__|__TARGET__" claude/prompts/*.md && echo "FOUND" || echo "clean"
```
Expected: `clean`.

- [ ] **Step 3: Verificar que aparecen las nuevas referencias**

```bash
cd ~/Files/rufino
grep -l '${RUFINO_VAULT_PATH}' claude/prompts/*.md | wc -l
```
Expected: `6` (los 6 prompts tienen al menos una referencia).

- [ ] **Step 4: Commit**

```bash
cd ~/Files/rufino
git add claude/prompts/
git commit -m "feat: add rufino prompts (transformed from claudeSetup)"
```

---

## Task 5: Copiar y transformar reglas (claude/rules/common/)

**Files:**
- Create: `claude/rules/common/obsidian-memory.md`, `claude/rules/common/rufino.md`
- Source: `/Users/val/Files/codeProjects/claudeSetup/claude-config/rules/common/{obsidian-memory,rufino}.md`

- [ ] **Step 1: Copiar y transformar con sed**

```bash
cd ~/Files/rufino
SRC=/Users/val/Files/codeProjects/claudeSetup/claude-config/rules/common

for f in obsidian-memory rufino; do
  sed -E \
    -e 's|__VAULT_PATH__|$VAULT_PATH|g' \
    -e 's|__DISPLAY_NAME__|$DISPLAY_NAME|g' \
    -e 's|/Users/val/Files/vaultlentino|$VAULT_PATH|g' \
    "$SRC/$f.md" > "claude/rules/common/$f.md"
done
```

- [ ] **Step 2: Verificar no hay paths absolutos de Val ni placeholders crudos**

```bash
cd ~/Files/rufino
grep -n -E "/Users/val|__VAULT_PATH__|__DISPLAY_NAME__|vaultlentino" claude/rules/common/*.md && echo "FOUND" || echo "clean"
```
Expected: `clean`.

- [ ] **Step 3: Agregar nota de "edit before install" al inicio de cada regla**

Anteponer este bloque al inicio de los dos archivos (después del primer encabezado si existe, sino al principio):

```markdown
> **NOTE (rufino-notes-and-memory install):** Antes de copiar esta regla a `~/.claude/rules/common/`, reemplazá manualmente los tokens `$VAULT_PATH` con tu path absoluto al vault y `$DISPLAY_NAME` con tu nombre. Las reglas se cargan como contexto plano por Claude — no hay shell expansion.

```

Usar este bash:
```bash
cd ~/Files/rufino
for f in claude/rules/common/obsidian-memory.md claude/rules/common/rufino.md; do
  TMP=$(mktemp)
  {
    echo '> **NOTE (rufino-notes-and-memory install):** Antes de copiar esta regla a `~/.claude/rules/common/`, reemplazá manualmente los tokens `$VAULT_PATH` con tu path absoluto al vault y `$DISPLAY_NAME` con tu nombre. Las reglas se cargan como contexto plano por Claude — no hay shell expansion.'
    echo ''
    cat "$f"
  } > "$TMP"
  mv "$TMP" "$f"
done
```

- [ ] **Step 4: Commit**

```bash
cd ~/Files/rufino
git add claude/rules/common/
git commit -m "feat: add obsidian-memory and rufino rules with install notes"
```

---

## Task 6: Copiar hook (claude/hooks/)

**Files:**
- Create: `claude/hooks/obsidianMemoryCheck.sh`
- Source: `/Users/val/Files/codeProjects/claudeSetup/claude-config/hooks/obsidianMemoryCheck.sh`

- [ ] **Step 1: Copiar tal cual (ya es portable)**

```bash
cd ~/Files/rufino
cp /Users/val/Files/codeProjects/claudeSetup/claude-config/hooks/obsidianMemoryCheck.sh claude/hooks/obsidianMemoryCheck.sh
chmod +x claude/hooks/obsidianMemoryCheck.sh
```

- [ ] **Step 2: Verificar sintaxis**

Run: `bash -n claude/hooks/obsidianMemoryCheck.sh && echo OK`
Expected: `OK`.

- [ ] **Step 3: Verificar que no tiene paths absolutos de Val**

Run: `grep "/Users/val" claude/hooks/obsidianMemoryCheck.sh && echo FOUND || echo clean`
Expected: `clean`.

- [ ] **Step 4: Commit**

```bash
cd ~/Files/rufino
git add claude/hooks/
git commit -m "feat: add obsidianMemoryCheck hook"
```

---

## Task 7: Copiar skill /remember (claude/commands/)

**Files:**
- Create: `claude/commands/remember.md`
- Source: `/Users/val/Files/codeProjects/claudeSetup/claude-config/commands/remember.md`

- [ ] **Step 1: Copiar y transformar (mismo patrón que reglas)**

```bash
cd ~/Files/rufino
sed -E \
  -e 's|__VAULT_PATH__|$VAULT_PATH|g' \
  -e 's|__DISPLAY_NAME__|$DISPLAY_NAME|g' \
  -e 's|/Users/val/Files/vaultlentino|$VAULT_PATH|g' \
  /Users/val/Files/codeProjects/claudeSetup/claude-config/commands/remember.md > claude/commands/remember.md
```

- [ ] **Step 2: Antepuesto nota de install**

```bash
cd ~/Files/rufino
TMP=$(mktemp)
{
  echo '> **NOTE (rufino-notes-and-memory install):** Antes de copiar esta skill a `~/.claude/commands/`, reemplazá `$VAULT_PATH` con tu path absoluto al vault y `$DISPLAY_NAME` con tu nombre.'
  echo ''
  cat claude/commands/remember.md
} > "$TMP"
mv "$TMP" claude/commands/remember.md
```

- [ ] **Step 3: Verificar no hay paths absolutos**

Run: `grep -E "/Users/val|__VAULT_PATH__|__DISPLAY_NAME__|vaultlentino" claude/commands/remember.md && echo FOUND || echo clean`
Expected: `clean`.

- [ ] **Step 4: Commit**

```bash
cd ~/Files/rufino
git add claude/commands/
git commit -m "feat: add /remember skill with install note"
```

---

## Task 8: Armar vault-skeleton/

**Files:**
- Create: `vault-skeleton/perfil.md`, `vault-skeleton/preferencias.md`, varios `.gitkeep` y subcarpetas.
- Source: `/Users/val/Files/codeProjects/claudeSetup/vault-skeleton/`

- [ ] **Step 1: Copiar el skeleton existente de claudeSetup tal cual**

```bash
cd ~/Files/rufino
cp -R /Users/val/Files/codeProjects/claudeSetup/vault-skeleton/. vault-skeleton/
```

- [ ] **Step 2: Mover perfil.md y preferencias.md de seed-notes/ al nivel raíz**

```bash
cd ~/Files/rufino
cp vault-skeleton/seed-notes/perfil.md vault-skeleton/perfil.md
cp vault-skeleton/seed-notes/preferencias.md vault-skeleton/preferencias.md
```

(Quedan también en `seed-notes/` como referencia. No se borran de ahí.)

- [ ] **Step 3: Pre-crear las carpetas vacías esperadas**

Crear con `.gitkeep` las carpetas que rufino/Claude llenan en runtime:

```bash
cd ~/Files/rufino
for d in conceptos proyectos sesiones inbox inbox/sources rufino/_archive rufino/_people _meta/ingest-applied _meta/ingest-discarded _meta/ingest-pending; do
  mkdir -p "vault-skeleton/$d"
  touch "vault-skeleton/$d/.gitkeep"
done
```

- [ ] **Step 4: Verificar contenidos esperados**

```bash
cd ~/Files/rufino
test -f vault-skeleton/perfil.md && echo "perfil OK" || echo "MISSING perfil"
test -f vault-skeleton/preferencias.md && echo "preferencias OK" || echo "MISSING preferencias"
test -f vault-skeleton/_meta/relationship-vocab.md && echo "relationship-vocab OK" || echo "MISSING relationship-vocab"
test -f vault-skeleton/rufino/_index.md && echo "_index OK" || echo "MISSING _index"
test -f vault-skeleton/conceptos/.gitkeep && echo "conceptos/.gitkeep OK" || echo "MISSING"
test -f vault-skeleton/proyectos/.gitkeep && echo "proyectos/.gitkeep OK" || echo "MISSING"
test -f vault-skeleton/sesiones/.gitkeep && echo "sesiones/.gitkeep OK" || echo "MISSING"
```
Expected: 7 líneas con `OK`.

- [ ] **Step 5: Verificar que no hay paths absolutos de Val en el skeleton**

```bash
cd ~/Files/rufino
grep -rln "/Users/val\|vaultlentino" vault-skeleton/ 2>/dev/null && echo "FOUND" || echo "clean"
```
Expected: `clean` (los seed-notes pueden tener referencias al display name pero no paths absolutos).

- [ ] **Step 6: Commit**

```bash
cd ~/Files/rufino
git add vault-skeleton/
git commit -m "feat: add vault skeleton with rufino/, conceptos/, proyectos/, sesiones/, _meta/, _templates/"
```

---

## Task 9: Armar plists (system/launchd/)

**Files:**
- Create: `system/launchd/com.user.rufino-{cron,light-cron,lint-cron}.plist`
- Source: `~/Library/LaunchAgents/com.val.rufino-{cron,light-cron,lint-cron}.plist`

- [ ] **Step 1: Copiar y transformar los 3 plists con sed**

```bash
cd ~/Files/rufino
SRC=~/Library/LaunchAgents

for f in rufino-cron rufino-light-cron rufino-lint-cron; do
  sed -E \
    -e 's|<string>com\.val\.(rufino-[a-z-]+)</string>|<string>com.user.\1</string>|g' \
    -e 's|/Users/val/\.claude/scripts/|__HOME__/.claude/scripts/|g' \
    -e 's|/Users/val/Files/codeProjects/Rufino/rufino-dashboard/logs/|__HOME__/.claude/logs/rufino/|g' \
    -e 's|<string>/Users/val/Files/vaultlentino</string>|<string></string>|g' \
    "$SRC/com.val.$f.plist" > "system/launchd/com.user.$f.plist"
done
```

- [ ] **Step 2: Verificar XML válido**

```bash
cd ~/Files/rufino
for f in system/launchd/*.plist; do
  plutil -lint "$f"
done
```
Expected: 3 líneas con `<path>: OK`.

- [ ] **Step 3: Verificar que no quedaron paths absolutos de Val**

```bash
cd ~/Files/rufino
grep -E "/Users/val|com\.val\.|rufino-dashboard" system/launchd/*.plist && echo "FOUND" || echo "clean"
```
Expected: `clean`.

- [ ] **Step 4: Verificar que los placeholders __HOME__ están presentes**

```bash
cd ~/Files/rufino
grep -c "__HOME__" system/launchd/*.plist
```
Expected: cada plist tiene al menos 3 ocurrencias (`ProgramArguments`, `StandardOutPath`, `StandardErrorPath`).

- [ ] **Step 5: Commit**

```bash
cd ~/Files/rufino
git add system/launchd/
git commit -m "feat: add launchd plists for the 3 rufino crons"
```

---

## Task 10: Escribir README.md

**Files:**
- Create: `README.md`

- [ ] **Step 1: Escribir el README completo**

Write `/Users/val/Files/rufino/README.md`:

````markdown
# rufino-notes-and-memory

> Sistema personal de memoria asistida por Claude Code + Obsidian. Procesa notas, genera triples tipados, promociona conceptos, extrae pendientes, mantiene índices, te recuerda guardar al vault al cerrar conversaciones.

## Cómo funciona

Dos capas que se combinan:

1. **Obsidian Memory** — Claude lee `perfil.md` y `preferencias.md` de tu vault al inicio de cada conversación, detecta en qué proyecto estás según tu CWD, y crea/actualiza `proyectos/<x>/overview.md` automáticamente. Una skill `/remember` decide la carpeta destino correcta (sesiones, decisiones, aprendizajes) cuando le pedís guardar algo.
2. **Rufino** — Tres crons procesan tu vault: convierten notas crudas en notas enriquecidas con augmentation, generan triples tipados desde wikilinks, promueven conceptos cuando aparecen ≥2 veces, extraen pendientes inline, mantienen índices.

Más un hook que al fin de cada conversación te pregunta si hay algo para guardar al vault.

## Prerrequisitos

- macOS o Linux con bash 3.2+.
- [Claude Code](https://claude.com/claude-code) instalado y autenticado.
- [Obsidian](https://obsidian.md/) instalado con un vault local.
- Plugin **obsidian-git** instalado en Obsidian, configurado para auto-commit cada hora (auto-backup del vault — no se distribuye con este repo).
- `jq` (`brew install jq` en macOS, `apt install jq` en Linux) — usado por el hook.
- `envsubst` (viene con `gettext` — en macOS `brew install gettext`, en Linux suele estar pre-instalado).

## Instalación

### 1. Cloná el repo

```bash
git clone https://github.com/<tu-user>/rufino-notes-and-memory.git ~/rufino-notes-and-memory
cd ~/rufino-notes-and-memory
```

### 2. Seteá tus variables de entorno

Agregá esto a tu `~/.zshenv` (o `~/.bashrc`):

```bash
export RUFINO_VAULT_PATH="/path/absoluto/a/tu/vault"
export RUFINO_DISPLAY_NAME="Tu Nombre"
export RUFINO_LOG_DIR="$HOME/.claude/logs/rufino"  # opcional, este es el default
```

Después: `source ~/.zshenv` (o abrí una shell nueva).

### 3. Copiá la config de Claude a `~/.claude/`

```bash
mkdir -p ~/.claude/{hooks,prompts,rules/common,scripts,commands} ~/.claude/logs/rufino
cp -n claude/hooks/* ~/.claude/hooks/
cp -n claude/prompts/* ~/.claude/prompts/
cp -n claude/rules/common/* ~/.claude/rules/common/
cp -n claude/scripts/* ~/.claude/scripts/
cp -n claude/commands/* ~/.claude/commands/
chmod +x ~/.claude/scripts/rufino-*.sh ~/.claude/hooks/*.sh
```

`cp -n` (no-clobber) no sobrescribe archivos pre-existentes. Si tenés tu propia config en `~/.claude/`, esos archivos sobreviven — resolvé conflictos a mano.

### 4. Editá las reglas y la skill /remember

Abrí los siguientes 3 archivos y reemplazá `$VAULT_PATH` por tu path absoluto y `$DISPLAY_NAME` por tu nombre:

- `~/.claude/rules/common/obsidian-memory.md`
- `~/.claude/rules/common/rufino.md`
- `~/.claude/commands/remember.md`

O con sed (más rápido):

```bash
for f in ~/.claude/rules/common/obsidian-memory.md ~/.claude/rules/common/rufino.md ~/.claude/commands/remember.md; do
  sed -i '' "s|\$VAULT_PATH|$RUFINO_VAULT_PATH|g; s|\$DISPLAY_NAME|$RUFINO_DISPLAY_NAME|g" "$f"
done
```

### 5. Copiá el skeleton al vault

```bash
cp -Rn vault-skeleton/. "$RUFINO_VAULT_PATH/"
```

**Importante:** abrí `$RUFINO_VAULT_PATH/perfil.md` y `$RUFINO_VAULT_PATH/preferencias.md` en tu editor y completalos. Claude los lee al inicio de cada conversación; si están vacíos, no va a tener contexto sobre quién sos ni cómo te gusta trabajar.

### 6. Instalá los crons (macOS / launchd)

Los plists vienen con placeholder `__HOME__`. Reemplazalo y copialos:

```bash
for f in system/launchd/*.plist; do
  sed "s|__HOME__|$HOME|g" "$f" > "$HOME/Library/LaunchAgents/$(basename "$f")"
done
```

Después, editá cada uno de los 3 plists en `~/Library/LaunchAgents/` y poné tu `RUFINO_VAULT_PATH` en el bloque `<key>EnvironmentVariables</key>` (hoy está vacío).

Cargá los servicios:

```bash
launchctl load ~/Library/LaunchAgents/com.user.rufino-cron.plist
launchctl load ~/Library/LaunchAgents/com.user.rufino-light-cron.plist
launchctl load ~/Library/LaunchAgents/com.user.rufino-lint-cron.plist
```

### 6b. Crontab equivalente (Linux)

En Linux con cron tradicional, agregá a tu crontab (`crontab -e`):

```cron
RUFINO_VAULT_PATH=/path/absoluto/a/tu/vault
RUFINO_DISPLAY_NAME=Tu Nombre

0 22 * * * /bin/bash ~/.claude/scripts/rufino-cron.sh
0 2 * * *  /bin/bash ~/.claude/scripts/rufino-light-cron.sh
0 3 * * *  /bin/bash ~/.claude/scripts/rufino-lint-cron.sh
```

## Verificación post-install

1. **Servicios cargados**:
   ```bash
   launchctl list | grep rufino
   ```
   Expected: 3 servicios `com.user.rufino-*`.

2. **Procesamiento manual de una nota**:
   ```bash
   echo "# Test\n\nNota cualquiera con un [[wikilink]]." > "$RUFINO_VAULT_PATH/rufino/test-$(date +%s).md"
   bash ~/.claude/scripts/rufino-cron.sh
   tail -50 "$RUFINO_LOG_DIR/rufino-cron.log"
   ```
   Expected: el log muestra "Rufino run" y "Rufino done", y la nota se movió a `rufino/<proyecto>/<tipo>/`.

3. **Auto-creación de overview de proyecto**:
   - Abrí Claude Code en un directorio que no sea conocido (un proyecto nuevo).
   - Pedile cualquier tarea.
   - Confirmá que se creó `$RUFINO_VAULT_PATH/proyectos/<x>/overview.md` y que `$RUFINO_VAULT_PATH/_meta/projectPaths.md` registró el path.

4. **Skill /remember**:
   - En una conversación con Claude, decile: "Guardá esta conversación como sesión".
   - Confirmá que se creó `$RUFINO_VAULT_PATH/sesiones/<YYYY-MM-DD-tema>.md`.

## Estructura del repo

```
rufino-notes-and-memory/
├── README.md
├── claude/
│   ├── hooks/obsidianMemoryCheck.sh
│   ├── prompts/rufino-{daily,light-cron,import-plan,process-single,reprocess,lint}.md
│   ├── rules/common/{obsidian-memory,rufino}.md
│   ├── scripts/rufino-{cron,light-cron,import-plan,process-single,lint-cron}.sh
│   └── commands/remember.md
├── vault-skeleton/
│   ├── perfil.md, preferencias.md
│   ├── rufino/, conceptos/, proyectos/, sesiones/, inbox/
│   ├── _meta/, _templates/, obsidian-config/, seed-notes/
└── system/launchd/com.user.rufino-{cron,light-cron,lint-cron}.plist
```

## Qué hace cada cron

| Cron | Horario | Qué hace |
|---|---|---|
| `rufino-cron` | 22:00 | Procesa notas crudas (`rufino/*.md` raíz): augmentation, tags, triples, mueve a `rufino/<proyecto>/<tipo>/`. |
| `rufino-light-cron` | 02:00 | Catch-up: notas que ya escribiste a mano fuera del flujo crudo. Agrega triples, promociona conceptos, registra personas, extrae pendientes. NO reescribe el cuerpo. |
| `rufino-lint-cron` | 03:00 | Valida invariantes del vault (frontmatter, wikilinks rotos, stale-inbox, etc.) y escribe un reporte JSON en `_meta/`. |

Scripts on-demand (sin cron):
- `rufino-import-plan.sh` — Procesa un doc importado siguiendo un JSON plan.
- `rufino-process-single.sh` — Procesa una sola nota fuera del cron.

## Componentes

- **Hook `obsidianMemoryCheck.sh`** — Al fin de cada conversación, te pide confirmar si hay algo para guardar al vault. Bloquea el stop una vez por sesión.
- **Skill `/remember`** — Mecanismo canónico de escritura al vault. Decide la carpeta destino según el tipo (sesión, decisión, aprendizaje, persona, concepto).
- **Regla `obsidian-memory.md`** — Instruye a Claude a leer `perfil.md` y `preferencias.md` al inicio, detectar proyecto por CWD, crear overview de proyecto nuevo, dispatchar subagent para escrituras al vault.
- **Regla `rufino.md`** — Instruye a Claude sobre cuándo invocar a Rufino y qué taxonomía usar.

## Cómo se llenan las carpetas que arrancan vacías

| Carpeta | Cuándo se llena |
|---|---|
| `conceptos/<x>.md` | Cron `rufino-light-cron` cuando un concepto aparece en ≥2 notas. |
| `proyectos/<x>/overview.md` | Claude lo crea cuando entrás a un CWD nuevo (regla obsidian-memory). |
| `sesiones/<YYYY-MM-DD-tema>.md` | Cuando le pedís a Claude "guardá esto como sesión" (skill `/remember`). |
| `rufino/<proyecto>/<tipo>/` | Cron `rufino-cron` mueve notas crudas procesadas. |
| `rufino/_people/<nombre>.md` | Cron `rufino-cron` cuando detecta una persona nueva. |

## Triples tipados

Las relaciones entre notas se guardan en el frontmatter de cada nota:

```yaml
triples:
  - { r: depends-on, o: decisionPricing }
  - { r: led-to, o: aprendizajeRsync }
```

El vocabulario canónico de relaciones está en `_meta/relationship-vocab.md` (incluido en el skeleton). Si querés agregar una relación nueva, edita ese archivo primero.

## Troubleshooting

- **El cron no corre**: chequeá `launchctl list | grep rufino`. Si aparece con `status` distinto de `0` o `-`, mirá el log: `tail -100 $RUFINO_LOG_DIR/rufino-*.log`. Causa común: `RUFINO_VAULT_PATH` no está exportada en el entorno del plist (revisar `<key>EnvironmentVariables</key>`).
- **Las reglas no se aplican**: confirmá que están en `~/.claude/rules/common/` y que Claude las carga (la regla obsidian-memory referencia `perfil.md` — pediéndole a Claude "leé mi perfil" debería buscar el archivo).
- **`/remember` no encuentra el vault**: confirmá que reemplazaste `$VAULT_PATH` en `~/.claude/commands/remember.md` con tu path real.
- **El hook bloquea siempre**: la primera vez por sesión bloquea con código 2 (es el comportamiento deseado). La segunda vez del mismo session_id pasa.
- **`envsubst: command not found`**: instalá `gettext` (`brew install gettext` en macOS).

## Mantenimiento

No hay sync automático entre este repo y `~/.claude/`. Si modificás archivos instalados y querés versionar los cambios, copialos de vuelta al repo y commiteá.

Para upgradear:
```bash
cd ~/rufino-notes-and-memory
git pull
# Repetí los pasos 3-6 de instalación (cp -n no pisa archivos modificados).
launchctl unload ~/Library/LaunchAgents/com.user.rufino-*.plist
launchctl load ~/Library/LaunchAgents/com.user.rufino-*.plist
```

## Desinstalación

```bash
launchctl unload ~/Library/LaunchAgents/com.user.rufino-cron.plist
launchctl unload ~/Library/LaunchAgents/com.user.rufino-light-cron.plist
launchctl unload ~/Library/LaunchAgents/com.user.rufino-lint-cron.plist
rm ~/Library/LaunchAgents/com.user.rufino-*.plist
rm ~/.claude/scripts/rufino-*.sh
rm ~/.claude/prompts/rufino-*.md
rm ~/.claude/rules/common/{obsidian-memory,rufino}.md
rm ~/.claude/hooks/obsidianMemoryCheck.sh
rm ~/.claude/commands/remember.md
```

El vault (`$RUFINO_VAULT_PATH`) **no se toca** en desinstalación — tu data sigue siendo tuya.

## Licencia

MIT.
````

- [ ] **Step 2: Verificar que se renderiza OK (sin errores de markdown)**

```bash
cd ~/Files/rufino
head -50 README.md
wc -l README.md
```
Expected: header se ve bien, el archivo tiene ~250 líneas.

- [ ] **Step 3: Commit**

```bash
cd ~/Files/rufino
git add README.md
git commit -m "docs: write installation README"
```

---

## Task 11: Verificación end-to-end

- [ ] **Step 1: Estructura final**

Run: `find ~/Files/rufino -type f -not -path '*/\.git/*' -not -path '*/docs/*' | sort`
Expected (aprox 30 archivos):
```
/Users/val/Files/rufino/.gitignore
/Users/val/Files/rufino/README.md
/Users/val/Files/rufino/claude/commands/remember.md
/Users/val/Files/rufino/claude/hooks/obsidianMemoryCheck.sh
/Users/val/Files/rufino/claude/prompts/rufino-daily.md
/Users/val/Files/rufino/claude/prompts/rufino-import-plan.md
/Users/val/Files/rufino/claude/prompts/rufino-light-cron.md
/Users/val/Files/rufino/claude/prompts/rufino-lint.md
/Users/val/Files/rufino/claude/prompts/rufino-process-single.md
/Users/val/Files/rufino/claude/prompts/rufino-reprocess.md
/Users/val/Files/rufino/claude/rules/common/obsidian-memory.md
/Users/val/Files/rufino/claude/rules/common/rufino.md
/Users/val/Files/rufino/claude/scripts/rufino-cron.sh
/Users/val/Files/rufino/claude/scripts/rufino-import-plan.sh
/Users/val/Files/rufino/claude/scripts/rufino-light-cron.sh
/Users/val/Files/rufino/claude/scripts/rufino-lint-cron.sh
/Users/val/Files/rufino/claude/scripts/rufino-process-single.sh
/Users/val/Files/rufino/system/launchd/com.user.rufino-cron.plist
/Users/val/Files/rufino/system/launchd/com.user.rufino-light-cron.plist
/Users/val/Files/rufino/system/launchd/com.user.rufino-lint-cron.plist
/Users/val/Files/rufino/vault-skeleton/...
```

- [ ] **Step 2: Lint global de scripts**

```bash
cd ~/Files/rufino
for f in claude/scripts/*.sh claude/hooks/*.sh; do bash -n "$f" && echo "$f OK"; done
```
Expected: todas las líneas con `OK`.

- [ ] **Step 3: Lint global de plists**

```bash
cd ~/Files/rufino
for f in system/launchd/*.plist; do plutil -lint "$f"; done
```
Expected: 3 `<path>: OK`.

- [ ] **Step 4: Sin paths absolutos de Val en ningún archivo del repo (excluyendo docs y .git)**

```bash
cd ~/Files/rufino
grep -rln "/Users/val\|vaultlentino\|com\.val\." \
  --exclude-dir=.git --exclude-dir=docs \
  . 2>/dev/null && echo "FOUND LEAKS" || echo "clean"
```
Expected: `clean`.

- [ ] **Step 5: Git log final**

Run: `cd ~/Files/rufino && git log --oneline`
Expected: 11 commits (spec + 10 tareas).

```
<hash> docs: write installation README
<hash> feat: add launchd plists for the 3 rufino crons
<hash> feat: add vault skeleton with rufino/, conceptos/, proyectos/, sesiones/, _meta/, _templates/
<hash> feat: add /remember skill with install note
<hash> feat: add obsidianMemoryCheck hook
<hash> feat: add obsidian-memory and rufino rules with install notes
<hash> feat: add rufino prompts (transformed from claudeSetup)
<hash> feat: add rufino scripts (transformed from claudeSetup)
<hash> chore: add gitignore
<hash> docs: initial design spec for rufino-notes-and-memory
```

(10 commits + el commit del spec = 11. Step 1 del Task 1 no commitea por sí solo.)

- [ ] **Step 6: Smoke test del install (opcional, manual)**

En una shell:
```bash
export RUFINO_VAULT_PATH="/tmp/rufino-test-vault"
export RUFINO_DISPLAY_NAME="Test User"
mkdir -p "$RUFINO_VAULT_PATH"
cp -Rn ~/Files/rufino/vault-skeleton/. "$RUFINO_VAULT_PATH/"
test -f "$RUFINO_VAULT_PATH/perfil.md" && echo "skeleton copy OK"
rm -rf "$RUFINO_VAULT_PATH"
```

- [ ] **Step 7: NO commit en este task** — verificación es read-only. Si todo da OK, el plan está completo.

---

## Resumen de archivos creados

| Path | Origen | Transformación |
|---|---|---|
| `.gitignore` | Nuevo | — |
| `README.md` | Nuevo | — |
| `claude/scripts/rufino-*.sh` (5) | claudeSetup | sed + envsubst injection |
| `claude/prompts/rufino-*.md` (6) | claudeSetup | sed: placeholders → `${ENV_VARS}` |
| `claude/rules/common/{obsidian-memory,rufino}.md` (2) | claudeSetup | sed + nota de install al inicio |
| `claude/hooks/obsidianMemoryCheck.sh` | claudeSetup | tal cual |
| `claude/commands/remember.md` | claudeSetup | sed + nota de install |
| `vault-skeleton/*` | claudeSetup + nuevos `.gitkeep` y `perfil.md`, `preferencias.md` al raíz | copia + agregados |
| `system/launchd/com.user.rufino-*.plist` (3) | ~/Library/LaunchAgents (com.val.*) | sed: paths → `__HOME__`, vault → "" |
