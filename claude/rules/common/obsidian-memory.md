> **NOTE (rufino-notes-and-memory install):** Antes de copiar esta regla a `~/.claude/rules/common/`, reemplazá manualmente los tokens `$VAULT_PATH` con tu path absoluto al vault y `$DISPLAY_NAME` con tu nombre. Las reglas se cargan como contexto plano por Claude — no hay shell expansion.

# Obsidian Memory

Vault de recuerdos: `$VAULT_PATH/`

## Al inicio de cada conversación

1. Leé `perfil.md` y `preferencias.md` del vault para saber quién es $DISPLAY_NAME y cómo le gusta trabajar.
2. Determiná en qué proyecto estás basándote en el CWD. Consultá `_meta/projectPaths.md` del vault para mapear el directorio actual a un proyecto.
3. Si hay match, leé el `overview.md` del proyecto y las decisiones recientes.
4. Si no hay match y el CWD es un proyecto nuevo, creá el overview y agregá el path a `_meta/projectPaths.md` automáticamente.
Si no hay match y no es un proyecto (ej: sesión desde `~`), usá solo el contexto global.

## Durante la conversación

SIEMPRE que detectes información valiosa, escribila en el vault SIN esperar a que $DISPLAY_NAME te lo pida. Esto incluye:
- Preferencias de trabajo, decisiones de estilo, cosas que le molestan
- Decisiones arquitectónicas o técnicas con su contexto
- Aprendizajes de debugging, soluciones no obvias
- Contexto de proyecto: qué es, quién trabaja, estado, stack
- Correcciones que $DISPLAY_NAME te hace (feedback)
- Info sobre $DISPLAY_NAME: su rol, background, responsabilidades

Hacelo en el momento — no acumules para el final de la sesión.
Si $DISPLAY_NAME te pide explícitamente que recuerdes algo, también.
Si algo que ya guardaste cambió, buscá la nota y actualizala.

## Cómo escribir al vault (importante)

Las escrituras al vault **NUNCA** se hacen con Edit/Write directo en el thread principal. $DISPLAY_NAME no quiere ver los diffs de cada save mientras trabaja — eso interrumpe el flujo visual de la conversación.

En su lugar, **dispatch un subagent en background** que haga toda la escritura adentro de su propio contexto:

```
Agent({
  description: "Save vault memory",
  subagent_type: "general-purpose",
  run_in_background: true,
  prompt: "Invocá la skill `/remember` y guardá lo siguiente en el vault siguiendo el manual operativo. [contexto autocontenido: qué guardar, tipo de nota, proyecto, wikilinks relevantes, fecha de hoy]"
})
```

Reglas:
- **Siempre `run_in_background: true`** — $DISPLAY_NAME sigue trabajando, no espera al subagent.
- **El prompt debe ser autocontenido**: el subagent no ve la conversación. Pasale toda la info necesaria (qué guardar, dónde, por qué importa, fecha).
- **No esperes ni muestres el resultado** del subagent. Si querés acusar recibo, una línea breve a $DISPLAY_NAME ("anoté X en el vault") después de dispatchar; nada más.
- **Las lecturas** del vault (perfil.md, overview.md, búsquedas, _people.md, _index.md de rufino) sí van en thread principal — solo las **escrituras** se hacen via subagent.
- **No invoques `/remember` directamente** en el thread principal: la skill hace Edits que renderizan diffs visibles.
