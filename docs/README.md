# Documentación — Rufino Framework

Índice de toda la documentación del proyecto.

## Para usar el framework

| Doc | Para qué sirve |
|---|---|
| [philosophy.md](philosophy.md) | Qué es Rufino, por qué existe, principios |
| [getting-started.md](getting-started.md) | Instalación + primer bootstrap paso a paso |
| [concepts.md](concepts.md) | Glosario: vault, adapter, primitive, manifest, transaction log, etc. |
| [use-cases.md](use-cases.md) | Verticales target con ejemplos concretos |
| [wizard.md](wizard.md) | Cómo conduce Claude el wizard conversacional |
| [cli-reference.md](cli-reference.md) | Cada comando, cada flag |
| [upgrading.md](upgrading.md) | Versionado, migrations, rollback |
| [troubleshooting.md](troubleshooting.md) | Problemas comunes y cómo resolverlos |

## Para contribuir / escribir adapters

| Doc | Para qué sirve |
|---|---|
| [architecture.md](architecture.md) | Overview de la arquitectura para desarrolladores |
| [writing-adapters.md](writing-adapters.md) | Guía para autores de adapters |
| [runtime.md](runtime.md) | Internals load-bearing: transaction log, sandbox, scheduler, secrets |
| [primitives/](primitives/) | Schema y contrato de cada primitive |
| [adapters/](adapters/) | Los 4 shapes de adapter en detalle |

## Cómo está organizado el repo

```
rufino-framework/
├── README.md                  # entry point del repo
├── install.sh, upgrade.sh     # entrypoints user
├── pyproject.toml             # package metadata (versión, deps, CLI binding)
├── migrations/                # bash scripts idempotentes para upgrades
├── src/rufino/
│   ├── cli.py                 # Click CLI — fachada thin sobre engines
│   ├── version.py
│   ├── engine/                # las 6 primitives
│   ├── wizard/                # bootstrap conversacional + materializer
│   ├── runtime/               # plumbing: tx log, sandbox, scheduler, secrets
│   ├── mcp_server/            # ask-rufino MCP server
│   └── helpers/               # API versionada para adapters
├── vault-skeleton/            # bootstrap del vault
├── system/launchd/            # plists de cron jobs
├── claude/                    # hooks/commands/skills que se copian a ~/.claude/
├── tests/                     # pytest
└── docs/                      # esto
```
