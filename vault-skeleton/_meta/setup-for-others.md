---
tags:
  - tipo/meta
created: 2026-04-13
updated: 2026-04-13
---

# Obsidian Memory System — Setup Guide

Pegá todo esto en una conversación nueva de Claude Code y dejá que Claude haga el resto.

---

## Prompt para Claude

```
Necesito que me configures un sistema de memoria persistente en Obsidian. El sistema tiene tres piezas que vos vas a crear. Antes de empezar, preguntame:

1. ¿Cuál es el path de mi vault de Obsidian? (donde querés que guarde las notas)
2. ¿Cómo me llamo?
3. ¿En qué proyectos trabajo?

Con esas respuestas, creá las tres piezas:

### Pieza 1: Regla global (~/.claude/rules/common/obsidian-memory.md)

Creá este archivo. Reemplazá {{VAULT_PATH}} con el path que te di:

# Obsidian Memory

Vault de recuerdos: `{{VAULT_PATH}}`

## Al inicio de cada conversación

1. Leé `perfil.md` y `preferencias.md` del vault para saber quién es el usuario y cómo le gusta trabajar.
2. Determiná en qué proyecto estás basándote en el CWD. Consultá `_meta/projectPaths.md` del vault para mapear el directorio actual a un proyecto.
3. Si hay match, leé el `overview.md` del proyecto y las decisiones recientes.
4. Si no hay match y el CWD es un proyecto nuevo, creá el overview y agregá el path a `_meta/projectPaths.md` automáticamente.
5. Si no hay match y no es un proyecto (ej: sesión desde `~`), usá solo el contexto global.

## Durante la conversación

SIEMPRE que detectes información valiosa, escribila en el vault SIN esperar a que te lo pidan. Esto incluye:
- Preferencias de trabajo, decisiones de estilo, cosas que le molestan
- Decisiones arquitectónicas o técnicas con su contexto
- Aprendizajes de debugging, soluciones no obvias
- Contexto de proyecto: qué es, quién trabaja, estado, stack
- Correcciones que te hacen (feedback)
- Info sobre el usuario: su rol, background, responsabilidades

Hacelo en el momento — no acumules para el final de la sesión.
Si te piden explícitamente que recuerdes algo, también.
Si algo que ya guardaste cambió, buscá la nota y actualizala.

Para escribir o actualizar notas: invocá la skill `/remember`.

### Pieza 2: Comando /remember (~/.claude/commands/remember.md)

Creá este archivo. Es el manual operativo completo para escribir en el vault. Debe incluir:

1. **Flujo de ejecución**: determinar tipo de nota → buscar si existe (Glob/Grep) → actualizar con Edit o crear con Write → actualizar wikilinks en notas relacionadas

2. **Estructura de directorios**:
   {{VAULT_PATH}}/
   ├── _meta/              # Docs del sistema
   ├── _templates/         # Templates
   ├── perfil.md           # Quién es el usuario
   ├── preferencias.md     # Cómo le gusta trabajar
   ├── stack.md            # Herramientas y tecnologías
   ├── proyectos/
   │   ├── <nombre>/
   │   │   ├── overview.md
   │   │   ├── decisiones/
   │   │   └── aprendizajes/
   │   └── ...
   └── sesiones/

3. **Nombres de archivo**: camelCase (decisionSupabaseAuth.md)

4. **Tags jerárquicos** (tres ejes en frontmatter YAML):
   - proyecto/ — proyecto/miApp, proyecto/backend, etc.
   - tipo/ — tipo/decision, tipo/preferencia, tipo/aprendizaje, tipo/debugging, tipo/perfil, tipo/feedback, tipo/sesion, tipo/overview, tipo/stack
   - tema/ — tema/arquitectura, tema/frontend, tema/backend, tema/auth, tema/testing, tema/devops, etc.

5. **Templates** para cada tipo de nota (perfil, preferencia, stack, overview de proyecto, decisión, aprendizaje, feedback, sesión). Cada template tiene:
   - Frontmatter YAML con tags, created, updated
   - Secciones relevantes al tipo
   - Sección "Relacionado:" al final con [[wikilinks]]

6. **Reglas de comportamiento**:
   - Silencioso: no anunciar cada escritura
   - Actualizar antes que crear: buscar existentes primero
   - Documentos vivos: editar y reestructurar, no solo append
   - Idioma: español para contenido, inglés para términos técnicos
   - Crear directorios de proyecto on demand

### Pieza 3: Stop hook (~/.claude/hooks/obsidianMemoryCheck.sh)

Creá este script bash y hacelo executable (chmod +x):

#!/bin/bash
set -euo pipefail
HOOK_INPUT=$(cat)
SESSION_ID=$(echo "$HOOK_INPUT" | jq -r '.session_id')
FLAG="/tmp/claude-memory-check-${SESSION_ID}"
if [ -f "$FLAG" ]; then
    rm -f "$FLAG"
    exit 0
fi
touch "$FLAG"
echo "OBSIDIAN MEMORY CHECK: revisá si hay algo para guardar en el vault antes de cerrar." >&2
exit 2

Después agregá el hook a ~/.claude/settings.json:

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

(Mergeá con el settings.json existente, no sobreescribas.)

### Pieza 4: Estructura inicial del vault

Creá estos directorios:
- {{VAULT_PATH}}/_meta/
- {{VAULT_PATH}}/_templates/
- {{VAULT_PATH}}/proyectos/
- {{VAULT_PATH}}/sesiones/

Creá el archivo _meta/projectPaths.md con una tabla vacía para mapear directorios a proyectos.

Después creá las notas semilla:
- perfil.md — con la info que me dieron sobre el usuario
- preferencias.md — preguntale cómo le gusta trabajar y documentalo
- stack.md — explorá su máquina (brew list, package.json globales, configs) y documentá su setup

Finalmente, explorá los proyectos que me mencionaron, leé sus repos, y creá un overview.md para cada uno.
```

---

## Qué tiene que hacer la persona

1. Tener Claude Code instalado
2. Tener un vault de Obsidian (o crear uno vacío)
3. Copiar el prompt de arriba y pegarlo en una conversación de Claude Code
4. Responder las 3 preguntas que Claude le hace
5. Dejar que Claude trabaje

Claude va a crear todo: la regla, el comando, el hook, la estructura del vault, las notas semilla, y los overviews de proyectos.
