---
tags:
  - tipo/meta
created: 2026-04-13
updated: 2026-04-13
---

# Obsidian Memory System — Design Spec

## Objetivo

Sistema para que Claude Code persista recuerdos sobre Val, sus proyectos y sus preferencias de trabajo en un vault de Obsidian. Los recuerdos se escriben de manera autónoma durante las conversaciones, sin esperar a que Val lo pida.

## Vault

- Path: `__VAULT_PATH__/`
- Uso exclusivo para recuerdos de Claude Code

## Estructura de carpetas

```
$VAULT_PATH/
├── _meta/                   # Documentación del sistema (este archivo)
├── _templates/              # Templates de notas
├── perfil.md                # Quién es Val, rol, background
├── preferencias.md          # Cómo le gusta trabajar con Claude
├── stack.md                 # Herramientas y tecnologías
├── proyectos/
│   ├── <nombre>/
│   │   ├── overview.md
│   │   ├── decisiones/
│   │   │   └── <decisionNombre>.md
│   │   └── aprendizajes/
│   │       └── <aprendizajeNombre>.md
│   └── ...
└── sesiones/                # Resúmenes de sesiones clave
    └── <YYYY-MM-DD-tema>.md
```

## Formato de notas

- Frontmatter YAML con `tags`, `created`, `updated`
- Nombres de archivo en camelCase: `decisionSupabaseAuth.md`
- Wikilinks `[[]]` en sección "Relacionado" al final + inline donde sea natural
- Español para contenido, términos técnicos en inglés sin traducir

### Tags jerárquicos (tres ejes)

- `proyecto/` — `proyecto/umbru`, `proyecto/cortex`, etc.
- `tipo/` — `tipo/decision`, `tipo/preferencia`, `tipo/aprendizaje`, `tipo/debugging`, `tipo/perfil`, `tipo/feedback`, `tipo/sesion`
- `tema/` — `tema/arquitectura`, `tema/frontend`, `tema/backend`, `tema/auth`, `tema/testing`, etc.

## Tres piezas del sistema

### 1. Regla global (`~/.claude/rules/common/obsidian-memory.md`)

Siempre cargada en contexto. Instrucción concisa que dice:
- SIEMPRE detectar información valiosa y escribirla SIN esperar
- Tipos de información a capturar: preferencias, decisiones, aprendizajes, contexto de proyecto, feedback
- Hacerlo en el momento, no acumular
- Si algo existente cambió, buscar la nota y actualizarla
- Para escribir: invocar skill `/remember`

### 2. Skill `/remember`

Se carga bajo demanda. Contiene:
- Path del vault y estructura de carpetas
- Templates para cada tipo de nota
- Taxonomía completa de tags
- Flujo de ejecución: detectar tipo -> buscar existente (Glob/Grep) -> crear o actualizar
- Instrucciones para actualizar wikilinks en notas relacionadas
- Comportamiento silencioso: no interrumpir el flujo de trabajo

### 3. Stop hook

Script bash que imprime un checklist de verificación cuando la sesión termina:
- ¿Aprendiste algo sobre Val o sus preferencias?
- ¿Se tomó alguna decisión importante?
- ¿Hubo debugging o solución no obvia?
- ¿Cambió algo de un proyecto?
- ¿Val te corrigió o confirmó algo?

Safety net, no obligación. Si la sesión fue trivial, no escribe nada.

## Templates de notas

### Perfil / Preferencias / Stack (raíz)

```markdown
---
tags:
  - tipo/perfil
created: YYYY-MM-DD
updated: YYYY-MM-DD
---

# Título

Contenido organizado por secciones relevantes.

---
Relacionado: [[nota1]] | [[nota2]]
```

### Overview de proyecto

```markdown
---
tags:
  - proyecto/<nombre>
  - tipo/overview
created: YYYY-MM-DD
updated: YYYY-MM-DD
---

# <Nombre del proyecto>

## Qué es
## Stack
## Estado actual
## Equipo
## Notas

---
Relacionado: [[stack]] | [[perfil]]
```

### Decisión

```markdown
---
tags:
  - proyecto/<nombre>
  - tipo/decision
  - tema/<tema>
created: YYYY-MM-DD
updated: YYYY-MM-DD
---

# Decisión: <título descriptivo>

## Contexto
## Opciones consideradas
## Decisión
## Consecuencias

---
Relacionado: [[<proyecto>Overview]] | [[otras notas]]
```

### Aprendizaje

```markdown
---
tags:
  - proyecto/<nombre>
  - tipo/aprendizaje
  - tema/<tema>
created: YYYY-MM-DD
updated: YYYY-MM-DD
---

# <Título descriptivo>

## Problema
## Qué descubrimos
## Solución
## Para recordar

---
Relacionado: [[notas relacionadas]]
```

### Feedback

```markdown
---
tags:
  - tipo/feedback
  - tema/<tema>
created: YYYY-MM-DD
updated: YYYY-MM-DD
---

# Feedback: <qué pasó>

## Corrección / Confirmación
## Por qué importa
## Cómo aplicarlo

---
Relacionado: [[preferencias]] | [[otras notas]]
```

### Sesión

```markdown
---
tags:
  - tipo/sesion
  - proyecto/<nombre>
created: YYYY-MM-DD
updated: YYYY-MM-DD
---

# Sesión: <tema principal>

## Qué hicimos
## Decisiones tomadas
## Pendientes
## Notas guardadas esta sesión

---
Relacionado: [[notas creadas/editadas]]
```

## Comportamiento

- **Autónomo**: Claude detecta y escribe sin que Val lo pida (95% del tiempo)
- **Bajo demanda**: Val puede pedir explícitamente que recuerde algo (5%)
- **Silencioso**: No anuncia cada escritura salvo que sea relevante al flujo
- **Vivo**: Las notas se actualizan cuando la información cambia, no son append-only
- **Cross-proyecto**: Las notas globales (perfil, preferencias, stack) informan el trabajo en todos los proyectos
