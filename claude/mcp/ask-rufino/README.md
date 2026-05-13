# ask-rufino MCP server

MCP server local que expone el vault de Obsidian de Val (Rufino) a cualquier sesión de Claude Code.

## Tools

| Tool | Qué hace |
|------|----------|
| `search_vault(query, limit=10)` | Full-text search con ranking por matches + mtime. |
| `find_person(name)` | Busca en `rufino/_people/`. Si match único, devuelve body. |
| `list_decisions(project?, limit=20)` | Lista `decision*.md` (filtrable por proyecto). |
| `list_facts(source?, since?, limit=50)` | Lista facts en `<source>/facts/`. |
| `read_note(path)` | Lee una nota por path relativo al vault. |
| `vault_stats()` | Totales: notas, proyectos, facts por source, personas, decisiones, sesiones. |

## Diseño

- **Transport**: stdio (estándar MCP). Claude Code lo invoca como subprocess.
- **Read-only**: ninguna tool escribe al vault.
- **Sin embeddings** (aún). Search es grep + ranking por matches y mtime. Cuando el ingestor de embeddings (Fase 4 paralelo) esté listo, se puede enhance `search_vault` con vector search — ver `docs/mcp-ask-rufino-notes.md`.
- **Path traversal**: `read_note` valida que el path resuelto esté dentro del vault.

## Config

| Env var | Default |
|---------|---------|
| `RUFINO_VAULT_PATH` | `/Users/val/Files/vaultlentino` |

## Install (manual)

```bash
cd ~/.claude/mcp/ask-rufino
npm install
```

O via script (recomendado — copia del repo al runtime dir y registra):

```bash
bash ~/Files/rufino/claude/scripts/setup-mcp-ask-rufino.sh
```

## Test (sin cliente MCP)

```bash
node ~/.claude/mcp/ask-rufino/index.js --test
```

Imprime un JSON con los resultados de `search_vault("umbru")`, `vault_stats()`, etc. Útil para validar sin tener que reiniciar Claude Code.

## Registración en Claude Code

Pegar en `~/.claude.json` dentro del objeto `mcpServers`:

```json
"ask-rufino": {
  "command": "node",
  "args": ["/Users/val/.claude/mcp/ask-rufino/index.js"],
  "env": {
    "RUFINO_VAULT_PATH": "/Users/val/Files/vaultlentino"
  }
}
```

Verificar:

```bash
claude mcp list
```

## Estructura

```
ask-rufino/
├── package.json
├── index.js                # entry point (stdio server + --test mode)
├── tools/
│   ├── util.js             # walkMarkdown, resolveSafe, snippet, etc.
│   ├── search_vault.js
│   ├── find_person.js
│   ├── list_decisions.js
│   ├── list_facts.js
│   ├── read_note.js
│   └── vault_stats.js
└── README.md
```
