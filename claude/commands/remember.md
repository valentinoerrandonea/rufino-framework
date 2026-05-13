> **NOTE (rufino-notes-and-memory install):** Antes de copiar esta skill a `~/.claude/commands/`, reemplazá `$VAULT_PATH` con tu path absoluto al vault y `$DISPLAY_NAME` con tu nombre.

# Manual Operativo: /remember

Este es el manual operativo para escribir memorias en el vault de Obsidian ubicado en `$VAULT_PATH/`. Cuando se invoca `/remember`, estas instrucciones determinan exactamente cómo leer, crear y actualizar notas.

---

## 1. Flujo de Ejecución

Seguir estos pasos en orden cada vez que se necesite guardar información:

### Paso 1 — Determinar el tipo de nota

Clasificar la información según uno de estos tipos:

| Tipo | Cuándo usarlo |
|------|---------------|
| `perfil` | Quién es $DISPLAY_NAME: datos personales, contexto profesional, forma de pensar |
| `preferencia` | Cómo le gusta trabajar: herramientas favoritas, flujos, opiniones sobre tecnologías |
| `stack` | Herramientas y tecnologías que usa: lenguajes, frameworks, servicios |
| `proyectoOverview` | Descripción general de un proyecto: qué es, estado, equipo, stack |
| `decision` | Una decisión técnica o de producto tomada en un proyecto |
| `aprendizaje` | Algo descubierto: un bug resuelto, un concepto entendido, una lección aprendida |
| `feedback` | Una corrección, confirmación o preferencia expresada explícitamente por $DISPLAY_NAME |
| `sesion` | Resumen de lo que se hizo durante una sesión de trabajo |

### Paso 2 — Buscar si ya existe una nota relacionada

Antes de crear nada, siempre buscar primero:

```
# Buscar por nombre de archivo
Glob("**/*.md", path="$VAULT_PATH/")

# Buscar por contenido relevante
Grep(pattern="<término clave>", path="$VAULT_PATH/", glob="**/*.md")
```

Si se conoce el proyecto o tema, buscar también dentro del directorio específico:

```
Glob("**/*.md", path="$VAULT_PATH/proyectos/<nombre>/")
```

### Paso 3 — Si la nota existe: actualizar

1. Leer la nota existente con `Read`
2. Identificar qué sección debe cambiar o qué información agregar
3. Usar `Edit` para hacer cambios precisos — no reescribir si no es necesario
4. Actualizar el campo `updated` en el frontmatter con la fecha de hoy (formato `YYYY-MM-DD`)
5. Las notas son documentos vivos: reestructurar, expandir y mejorar según convenga

### Paso 4 — Si no existe: crear

1. Determinar el directorio correcto según la estructura del vault (ver sección 3)
2. Si es el primer archivo de un proyecto nuevo, crear antes los directorios necesarios:
   - `proyectos/<nombre>/`
   - `proyectos/<nombre>/decisiones/`
   - `proyectos/<nombre>/aprendizajes/`
3. Elegir el template correcto (ver sección 6)
4. Usar `Write` para crear la nota con el contenido completo
5. Nombre de archivo en camelCase (ver sección 4)

### Paso 5 — Detectar personas y conceptos

Al crear o actualizar una nota, revisá si menciona:

**Personas:**
1. Si aparece un nombre, buscar `$VAULT_PATH/rufino/_people/<nombre>.md`
2. Si existe el archivo: agregar tag `persona/<nombre>` a la nota, y agregar la nota a la sección "Menciones en notas" del archivo de la persona
3. Si NO existe: preguntar al usuario quién es (nombre, relación, proyectos) y crear el archivo. Después actualizar el índice `_people.md`

**Conceptos técnicos:**
Escanear la nota por entidades técnicas específicas (herramientas, técnicas, tecnologías con nombre propio). Para cada concepto identificado, agregar tag `concepto/<nombre-kebab-case>`.

Regla: concepto es algo que alguien googlearía la primera vez que lo viera.

### Paso 6 — Actualizar wikilinks

Después de crear o modificar una nota:

1. Pensar: ¿qué otras notas del vault deberían referenciar esta nota nueva/actualizada?
2. Buscar esas notas con `Glob` o `Grep`
3. Leerlas y agregar `[[wikilink]]` en su sección `Relacionado:` si aún no está
4. Agregar también wikilinks inline en el cuerpo del texto cuando la referencia sea natural

---

## 2. Reglas de Comportamiento

- **Silencioso por defecto**: No anunciar cada escritura. Solo mencionarlo si es relevante para el flujo de la conversación.
- **Actualizar antes que crear**: Siempre buscar notas existentes antes de crear una nueva. Si ya existe una nota sobre el mismo tema, actualizarla.
- **Documentos vivos**: Las notas no son append-only. Editar, reestructurar y mejorar según la información evolucione.
- **Idioma**: Español para el contenido. Inglés para términos técnicos sin traducción natural (stack, hook, middleware, API, render, deploy, etc.).
- **Fechas en frontmatter**: Siempre poner `created` al crear. Siempre actualizar `updated` al editar.
- **Crear directorios de proyecto on demand**: Al escribir la primera nota de un proyecto nuevo, crear `proyectos/<nombre>/`, `proyectos/<nombre>/decisiones/`, `proyectos/<nombre>/aprendizajes/`.

---

## 3. Estructura de Directorios

```
$VAULT_PATH/
├── _meta/                          # Documentación del sistema del vault
├── _templates/                     # Templates de notas (referencia)
├── perfil.md                       # Quién es $DISPLAY_NAME
├── preferencias.md                 # Cómo le gusta trabajar
├── stack.md                        # Herramientas y tecnologías
├── proyectos/
│   ├── <nombre>/                   # Una carpeta por proyecto
│   │   ├── overview.md             # Descripción general del proyecto
│   │   ├── decisiones/
│   │   │   └── <decisionNombre>.md
│   │   └── aprendizajes/
│   │       └── <aprendizajeNombre>.md
│   └── ...
└── sesiones/
    └── <YYYY-MM-DD-tema>.md        # Una nota por sesión de trabajo
```

### Dónde va cada tipo de nota

| Tipo | Ruta |
|------|------|
| `perfil` | `$VAULT_PATH/perfil.md` |
| `preferencia` | `$VAULT_PATH/preferencias.md` |
| `stack` | `$VAULT_PATH/stack.md` |
| `proyectoOverview` | `$VAULT_PATH/proyectos/<nombre>/overview.md` |
| `decision` | `$VAULT_PATH/proyectos/<nombre>/decisiones/<decisionNombre>.md` |
| `aprendizaje` | `$VAULT_PATH/proyectos/<nombre>/aprendizajes/<aprendizajeNombre>.md` |
| `feedback` | `$VAULT_PATH/preferencias.md` (sección de feedback) o nota separada si es sustancial |
| `sesion` | `$VAULT_PATH/sesiones/<YYYY-MM-DD-tema>.md` |

---

## 4. Nombres de Archivo

### Reglas

- **camelCase** para todos los nombres de archivo
- **Lowercase** para nombres de carpetas de proyectos
- **Prefijo de fecha** solo para sesiones

### Ejemplos correctos

```
# Decisiones
decisionSupabaseAuth.md
decisionMigrarANextjs.md
decisionArquitecturaMonorepo.md

# Aprendizajes
aprendizajeRaceConditionWebsocket.md
aprendizajeCachingConRedis.md
aprendizajeDebuggingMemoryLeak.md

# Proyectos (carpetas en lowercase)
proyectos/umbru/
proyectos/cortex/
proyectos/claudeSetup/
proyectos/miProyecto/

# Sesiones (fecha + tema en camelCase)
2026-04-13-sistemaDeNotificaciones.md
2026-04-14-refactorAuthModule.md
```

---

## 5. Taxonomía de Tags — 5 ejes

Usar siempre los ejes que apliquen. Cada nota debería tener 4-8 tags distribuidos entre los ejes.

### Eje proyecto/
Identifica a qué proyecto pertenece la nota. Si es posible, incluye la arista (sub-área).

```
proyecto/umbru
proyecto/oiko/producto
proyecto/oiko/infraestructura
proyecto/percha/ml
proyecto/telus/rpa-sap
proyecto/rufino/infraestructura
```

### Eje tipo/
Identifica qué tipo de nota es.

```
tipo/decision
tipo/preferencia
tipo/aprendizaje
tipo/debugging
tipo/perfil
tipo/feedback
tipo/sesion
tipo/overview
tipo/stack
tipo/persona
```

### Eje tema/
Identifica el área técnica o temática amplia.

```
tema/arquitectura
tema/frontend
tema/backend
tema/auth
tema/testing
tema/devops
tema/performance
tema/ux
tema/database
tema/api
tema/infra
tema/seguridad
tema/ai
tema/mobile
tema/tooling
tema/finanzas
tema/productividad
tema/negocios
```

### Eje persona/
Identifica personas involucradas en la nota (decisión tomada con alguien, aprendizaje de alguien, feedback de alguien, etc.).

```
persona/alejo
persona/gabi
persona/piero
persona/mati
persona/juan
persona/meli
persona/diego
```

Si mencionás una persona nueva: crear el archivo `$VAULT_PATH/rufino/_people/<nombre>.md` y agregar al índice `$VAULT_PATH/rufino/_people.md`.

### Eje concepto/
Identifica conceptos técnicos o específicos que aparecen en la nota. Un concepto es algo que buscarías en Google si lo vieras por primera vez.

```
concepto/embeddings
concepto/rls
concepto/mlx
concepto/polling-visual
concepto/supabase
concepto/docker-compose
concepto/nextjs-app-router
concepto/rag
```

**Regla:** no usar conceptos amplios como `concepto/arquitectura` (eso va en `tema/`). Los conceptos son específicos: herramientas, técnicas, nombres propios de tecnología.

---

## 6. Templates de Notas

### Template: Perfil / Preferencias / Stack
Para las notas raíz globales (`perfil.md`, `preferencias.md`, `stack.md`).

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

### Template: Overview de proyecto
Para `proyectos/<nombre>/overview.md`.

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

### Template: Decisión
Para `proyectos/<nombre>/decisiones/<decisionNombre>.md`.

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
Relacionado: [[<nombre>Overview]] | [[otras notas]]
```

### Template: Aprendizaje
Para `proyectos/<nombre>/aprendizajes/<aprendizajeNombre>.md`.

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

### Template: Feedback
Para notas de feedback cuando es sustancial. Las pequeñas correcciones van en `preferencias.md`.

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

### Template: Sesión
Para `sesiones/<YYYY-MM-DD-tema>.md`.

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

---

## 7. Convenciones de Wikilinks

### Sección Relacionado
Siempre incluir al final de cada nota una sección `Relacionado:` con links a notas relacionadas:

```markdown
---
Relacionado: [[perfil]] | [[stack]] | [[umbruOverview]]
```

- Usar `|` como separador entre links
- Incluir entre 1 y 5 links relevantes
- No poner links vacíos o placeholders

### Wikilinks inline
Usar `[[wikilink]]` dentro del cuerpo del texto cuando se hace referencia natural a otra nota:

```markdown
Esta decisión surgió del trabajo en [[umbruOverview]] y afecta la forma en que
manejamos auth, similar a lo documentado en [[decisionSupabaseAuth]].
```

### Links bidireccionales
Al crear una nota nueva, verificar si notas existentes deberían referenciarla:

1. Buscar notas del mismo proyecto
2. Buscar notas del mismo tema
3. Leer las candidatas y agregar el wikilink en su sección `Relacionado:` si corresponde

---

## 8. Referencia Rápida

### Checklist al crear una nota nueva
- [ ] Tipo identificado
- [ ] Búsqueda de duplicados realizada
- [ ] Directorio correcto
- [ ] Nombre de archivo en camelCase
- [ ] Template correcto aplicado
- [ ] Tags correctos (proyecto/ + tipo/ + tema/)
- [ ] Fechas `created` y `updated` con la fecha de hoy
- [ ] Sección `Relacionado:` con wikilinks
- [ ] Notas existentes actualizadas con link de vuelta

### Checklist al actualizar una nota existente
- [ ] Nota leída antes de editar
- [ ] Campo `updated` actualizado a hoy
- [ ] Edición precisa con `Edit` (no reescribir todo)
- [ ] Wikilinks nuevos agregados si aplica
