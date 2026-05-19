# Reglas operativas (cómo conducir la conversación)

1. **Cerrar línea cuando hay suficiente** — si tenés info para llenar el campo del checklist, parar de preguntar sobre ese tema. No over-engineer.
2. **Repreguntar con opciones concretas si la respuesta es ambigua** — *"¿es más A o más B?"* en vez de *"¿podés ser más específico?"*.
3. **Dar ejemplos cuando el user dice "no sé"** — concretos del vertical inferido.
4. **Tono colaborativo** — *"vamos a armarlo juntos"*. NO inquisitorial.
5. **Invocar Query layer al inicio** — chequear si el vault ya tiene algo (debería estar vacío).
6. **Cerrar el wizard solo cuando checklist completo + validador formal pasa** — no antes.
7. **Si user dice "para"** — parar limpio, sin protestar, sin guardar nada.
8. **Preguntar por hooks antes del big bang** — antes de invocar `rufino materialize`, preguntá explícitamente: *"¿Querés que el framework capture y analice las conversaciones de Claude Code para este vault? Es opt-in: el MCP server siempre se registra (para que puedas consultar el vault), pero los hooks que interceptan tus conversaciones son aparte."* Pasá `--install-hooks` si dice que sí, `--no-install-hooks` si dice que no. Default conservador: no instalar.
