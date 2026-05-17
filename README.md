# Rufino Framework

> Meta-arquitectura A2P para construir productos de gestión de conocimiento personal a través de una conversación con Claude Code.

## Instalación

Requisitos: macOS o Linux, Python 3.11+, Claude Code CLI instalado y autenticado.

```bash
git clone https://github.com/<owner>/rufino-framework.git ~/rufino-framework
cd ~/rufino-framework
./install.sh
```

El instalador:
- Instala las dependencias Python (`pip install -e .`)
- Registra `rufino` en tu `$PATH`
- Crea `~/.rufino/` con la estructura base
- Registra el MCP server `ask-rufino` en `~/.claude.json`

Al terminar, te dice:

```
Listo. Para empezar, corré: rufino bootstrap
```

## Quick start

```bash
rufino bootstrap          # entrevista conversacional con Claude
                          # → al final, materializa tu vault
```

Después, usá tu vault como siempre: tirá notas a `inbox/`, conversá con
Claude Code en cualquier proyecto, recibí los digests por email.

## Comandos disponibles

| Comando | Para qué sirve |
|---|---|
| `rufino bootstrap` | Iniciar el wizard conversacional |
| `rufino version` | Imprimir la versión instalada |
| `rufino ingest <adapter>` | Correr un Ingest adapter una vez |
| `rufino process <note> --vault X --mode light` | Procesar una nota (light mode) |
| `rufino output <adapter>` | Correr un Output adapter una vez |
| `rufino query "..." --vault X` | Buscar en el vault |
| `rufino qa-poll --vault X --state-dir Y` | Procesar respuestas a preguntas |
| `rufino mcp-server --vault X` | Levantar MCP server stdio |
| `rufino install-memory-loop <adapter_dir> --vault X --claude-home Y` | Instalar un Memory loop adapter |
| `rufino materialize --spec <file> ...` | Materializar un vault desde una WizardSpec JSON |

## Upgrade

```bash
cd ~/rufino-framework
git pull
./upgrade.sh
```

## Documentación

- [Arquitectura del framework](docs/superpowers/specs/2026-05-16-rufino-framework-design.md)
- [Paper académico](docs/papers/2026-05-16-rufino-framework-paradigm-es.md)
- [Cómo escribir adapters](docs/adapters/)
- [API de las primitives](docs/primitives/)

## Licencia

(TBD por el dueño del repo privado.)
