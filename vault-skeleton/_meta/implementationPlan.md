# Obsidian Memory System — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a three-piece system (global rule + skill + stop hook) that makes Claude Code autonomously persist memories in an Obsidian vault.

**Architecture:** A global rule keeps Claude alert to capture-worthy information. A `/remember` command provides the full operational manual (templates, tags, structure). A Stop hook blocks session end once to force a final memory check.

**Tech Stack:** Claude Code rules, commands, hooks, bash, Obsidian (markdown vault)

---

### Task 1: Create vault directory structure

**Files:**
- Create: `__VAULT_PATH__/_templates/` (directory)
- Create: `__VAULT_PATH__/proyectos/` (directory)
- Create: `__VAULT_PATH__/sesiones/` (directory)

- [ ] **Step 1: Create all directories**

```bash
mkdir -p __VAULT_PATH__/_templates
mkdir -p __VAULT_PATH__/proyectos
mkdir -p __VAULT_PATH__/sesiones
```

- [ ] **Step 2: Verify structure**

```bash
find __VAULT_PATH__ -type d | sort
```

Expected:
```
__VAULT_PATH__
__VAULT_PATH__/.obsidian
__VAULT_PATH__/_meta
__VAULT_PATH__/_templates
__VAULT_PATH__/proyectos
__VAULT_PATH__/sesiones
```

---

### Task 2: Write the global rule

**Files:**
- Create: `~/.claude/rules/common/obsidian-memory.md`

- [ ] **Step 1: Write the rule file**

Write to `~/.claude/rules/common/obsidian-memory.md`:

```markdown
# Obsidian Memory

Mantenés un vault de recuerdos en `__VAULT_PATH__/`.

SIEMPRE que detectes información valiosa durante la conversación, escribila en el vault SIN esperar a que Val te lo pida. Esto incluye:
- Preferencias de trabajo, decisiones de estilo, cosas que le molestan
- Decisiones arquitectónicas o técnicas con su contexto
- Aprendizajes de debugging, soluciones no obvias
- Contexto de proyecto: qué es, quién trabaja, estado, stack
- Correcciones que Val te hace (feedback)
- Info sobre Val: su rol, background, responsabilidades

Hacelo en el momento — no acumules para el final de la sesión.
Si Val te pide explícitamente que recuerdes algo, también.
Si algo que ya guardaste cambió, buscá la nota y actualizala.

Para escribir o actualizar notas: invocá la skill `/remember`.
```

- [ ] **Step 2: Verify the file exists and is readable**

```bash
cat ~/.claude/rules/common/obsidian-memory.md
```

---

### Task 3: Write the `/remember` command

**Files:**
- Create: `~/.claude/commands/remember.md`

- [ ] **Step 1: Create the commands directory**

```bash
mkdir -p ~/.claude/commands
```

- [ ] **Step 2: Write the command file**

Write to `~/.claude/commands/remember.md` the full operational manual including:
- Vault path and folder structure
- Complete tag taxonomy (proyecto/, tipo/, tema/)
- Execution flow: determine type → search existing (Glob/Grep) → create or update
- All note templates (perfil, preferencia, stack, proyectoOverview, decision, aprendizaje, feedback, sesion)
- Wikilink conventions
- camelCase file naming
- Silent behavior instructions
- Instructions for updating related notes' wikilinks

Full content specified in Step 2 of implementation (too long to inline here — see design spec for all templates).

- [ ] **Step 3: Verify the command is discoverable**

```bash
ls -la ~/.claude/commands/remember.md
```

---

### Task 4: Write the Stop hook script

**Files:**
- Create: `~/.claude/hooks/obsidianMemoryCheck.sh`

- [ ] **Step 1: Create the hooks directory**

```bash
mkdir -p ~/.claude/hooks
```

- [ ] **Step 2: Write the hook script**

Write to `~/.claude/hooks/obsidianMemoryCheck.sh`:

```bash
#!/bin/bash
set -euo pipefail

# Read hook input from stdin
HOOK_INPUT=$(cat)
SESSION_ID=$(echo "$HOOK_INPUT" | jq -r '.session_id')
FLAG="/tmp/claude-memory-check-${SESSION_ID}"

# If we've already been reminded this session, allow the stop
if [ -f "$FLAG" ]; then
    rm -f "$FLAG"
    exit 0
fi

# First time: remind and block
touch "$FLAG"
cat >&2 <<'REMINDER'
OBSIDIAN MEMORY CHECK — Revisá la conversación antes de cerrar:
- ¿Aprendiste algo sobre Val o sus preferencias?
- ¿Se tomó alguna decisión importante?
- ¿Hubo debugging o solución no obvia?
- ¿Cambió algo de un proyecto (stack, estado, equipo)?
- ¿Val te corrigió o confirmó algo sobre cómo trabajar?
Si hay algo que no guardaste, invocá /remember ahora.
Si ya guardaste todo, respondé normalmente y el hook te deja pasar.
REMINDER
exit 2
```

- [ ] **Step 3: Make it executable**

```bash
chmod +x ~/.claude/hooks/obsidianMemoryCheck.sh
```

- [ ] **Step 4: Verify the script runs**

```bash
echo '{"session_id":"test123"}' | ~/.claude/hooks/obsidianMemoryCheck.sh 2>&1; echo "exit: $?"
```

Expected: reminder text + `exit: 2` (first run), then:

```bash
echo '{"session_id":"test123"}' | ~/.claude/hooks/obsidianMemoryCheck.sh 2>&1; echo "exit: $?"
```

Expected: no output + `exit: 0` (second run, flag exists)

- [ ] **Step 5: Clean up test flag**

```bash
rm -f /tmp/claude-memory-check-test123
```

---

### Task 5: Configure the Stop hook in settings.json

**Files:**
- Modify: `~/.claude/settings.json`

- [ ] **Step 1: Add the hooks configuration**

Add to the existing `~/.claude/settings.json`:

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "$HOME/.claude/hooks/obsidianMemoryCheck.sh",
            "timeout": 30
          }
        ]
      }
    ]
  }
}
```

Merge with existing keys — do NOT overwrite existing settings.

- [ ] **Step 2: Verify JSON is valid**

```bash
jq . ~/.claude/settings.json
```

Expected: valid JSON with both existing keys and new `hooks` key.

---

### Task 6: Write seed notes

**Files:**
- Create: `__VAULT_PATH__/perfil.md`
- Create: `__VAULT_PATH__/preferencias.md`
- Create: `__VAULT_PATH__/stack.md`

- [ ] **Step 1: Write perfil.md**

Based on what we know from this conversation and the vault contents (Umbru project, embeddings work, cortex).

- [ ] **Step 2: Write preferencias.md**

Based on what we've established: autonomous memory, proactive behavior, español + english terms, camelCase files, etc.

- [ ] **Step 3: Write stack.md**

Based on observable setup: Claude Code Opus 1M, Obsidian, superpowers plugin, agent teams, etc.

- [ ] **Step 4: Verify all seed notes exist and have valid frontmatter**

```bash
for f in perfil preferencias stack; do
  echo "=== $f.md ===" 
  head -8 "__VAULT_PATH__/$f.md"
  echo
done
```

---

### Task 7: Verify the complete system

- [ ] **Step 1: Verify vault structure is complete**

```bash
find __VAULT_PATH__ -type f -name "*.md" | sort
```

- [ ] **Step 2: Verify rule is in place**

```bash
ls ~/.claude/rules/common/obsidian-memory.md
```

- [ ] **Step 3: Verify command is in place**

```bash
ls ~/.claude/commands/remember.md
```

- [ ] **Step 4: Verify hook is configured**

```bash
jq '.hooks' ~/.claude/settings.json
```

- [ ] **Step 5: Verify hook script is executable**

```bash
ls -la ~/.claude/hooks/obsidianMemoryCheck.sh
```
