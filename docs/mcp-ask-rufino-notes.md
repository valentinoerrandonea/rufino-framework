# MCP `ask-rufino` — notas operativas

MCP server local que expone el vault de Obsidian a cualquier sesión de Claude Code (no solo cuando trabajás en un directorio específico). Eso resuelve la limitación de que Rufino vivía solo en `~/Files/vaultlentino` y los hooks/skills de auto-load no aplicaban desde sesiones lanzadas en otros paths.

## 1. Install

Opción A — script (recomendado):

```bash
bash ~/Files/rufino/claude/scripts/setup-mcp-ask-rufino.sh
```

Eso:

1. Copia `claude/mcp/ask-rufino/` del repo a `~/.claude/mcp/ask-rufino/`.
2. Corre `npm install` ahí.
3. Muestra el JSON block para `~/.claude.json`.

Opción B — manual:

```bash
mkdir -p ~/.claude/mcp/ask-rufino
cp -R ~/Files/rufino/claude/mcp/ask-rufino/. ~/.claude/mcp/ask-rufino/
cd ~/.claude/mcp/ask-rufino && npm install
```

## 2. Test (sin cliente MCP)

```bash
node ~/.claude/mcp/ask-rufino/index.js --test
```

Salida esperada — JSON con resultados de:
- `search_vault("umbru", limit=10)` — top 10 con `path`, `title`, `snippet`, `matches`, `mtime`.
- `vault_stats()` — totales del vault.
- `list_decisions("umbru", limit=5)`.
- `find_person("alejandro")`.
- `list_facts(source="spotify", limit=3)`.

Si `search_vault` devuelve 0 matches → revisar que `RUFINO_VAULT_PATH` apunte al vault correcto (default `/Users/val/Files/vaultlentino`).

El test mode no requiere `@modelcontextprotocol/sdk` instalado — corre las tool handlers directamente. Eso permite validar la lógica del server aunque `npm install` falle por algún issue de red.

## 3. Registración en Claude Code

Editar `~/.claude.json` y pegar dentro del objeto `mcpServers`:

```json
"ask-rufino": {
  "command": "node",
  "args": ["/Users/val/.claude/mcp/ask-rufino/index.js"],
  "env": {
    "RUFINO_VAULT_PATH": "/Users/val/Files/vaultlentino"
  }
}
```

> Importante: **no editar `~/.claude.json` programáticamente** — es config global de Claude Code de Val y hay otras cosas ahí. Val pega el bloque a mano.

## 4. Verificación

Después de pegar el JSON y reiniciar Claude Code:

```bash
claude mcp list
```

Debería listar `ask-rufino` como conectado. Si no aparece:

- Verificar que `node ~/.claude/mcp/ask-rufino/index.js` arranca sin error (debería quedarse colgado esperando stdin — Ctrl+C para salir; ese es el comportamiento normal de un servidor stdio).
- Si tira "Cannot find package @modelcontextprotocol/sdk" → falta `npm install`.
- Logs de Claude Code en `~/Library/Logs/Claude/` (macOS).

En una sesión nueva, podés probar:

```
¿Quién es alejandro abraham? (debería usar find_person)
¿Qué decisiones hay en umbru? (debería usar list_decisions)
Buscá "augmentation" en el vault. (debería usar search_vault)
```

## 5. Diseño y decisiones

- **Node vs Python**: Node. SDK MCP de Anthropic más maduro en TS/JS; vault es solo I/O de archivos así que performance no importa.
- **Search**: grep + ranking por número de matches y mtime. Sin tokenización fancy. Suficiente para el volumen actual (~325 archivos, escala hasta varios miles sin issues).
- **Stdio**: estándar MCP. Claude Code lanza el proceso por sesión.
- **Read-only**: ninguna tool escribe al vault. Las escrituras siguen yendo via la skill `/remember` + Edit.
- **Sin caché**: el vault cambia constantemente (ingestors + escrituras manuales). Re-scan en cada llamada. Si esto se hace lento, agregar caché in-memory con invalidación por mtime del root.

## 6. Futuro — enhance con embeddings

Otro agente Fase 4 (paralelo) está construyendo embeddings sobre el vault. Cuando exista, `search_vault` se puede enhance así:

1. Detectar si existe `~/.claude/cache/rufino-embeddings/index.json` (o similar) al arrancar.
2. Si existe, agregar un parámetro `mode: "lexical" | "semantic" | "hybrid"` (default `"hybrid"`).
3. `semantic`: cargar embeddings, embedear `query`, top-K cosine similarity.
4. `hybrid`: combinar score lexical (matches normalizados) + score semántico (cosine).
5. Mantener el path actual (lexical) como fallback si los embeddings no están.

No tocar el resto de las tools — solo `search_vault.js`.

## 7. Troubleshooting

| Síntoma | Causa probable | Fix |
|---------|---------------|-----|
| `claude mcp list` no muestra `ask-rufino` | JSON mal formado en `~/.claude.json` | Validar con `cat ~/.claude.json \| jq .mcpServers` |
| Error "Cannot find package @modelcontextprotocol/sdk" | falta `npm install` | `cd ~/.claude/mcp/ask-rufino && npm install` |
| `search_vault` devuelve 0 | `RUFINO_VAULT_PATH` mal seteado | Confirmar `env.RUFINO_VAULT_PATH` en el JSON block |
| `find_person` devuelve 0 | Vault no tiene `rufino/_people/` | Confirmar estructura del vault |
| Server arranca pero tools no aparecen en sesión | Claude Code no recargó MCPs | Reiniciar Claude Code completamente |
