# Vertical config adapter

Shape usado por: **Memory loop**.

## Estructura

```
~/.rufino/adapters/memory_loop/<adapter_name>/
├── manifest.yaml
└── rules/
    ├── <vertical>-vocabulary.md
    └── <vertical>-conventions.md
```

## Qué hace

A diferencia de los Worker adapters (que ejecutan código), el Vertical config es **declarativo + reglas para Claude**. El framework instala las reglas en `~/.claude/rules/common/` para que Claude las lea al iniciar conversación.

## Campos del manifest

- `adapter_name`, `vertical_name`
- `entity_types`: lista de tipos de notas que tu vertical maneja
- `note_destinations`: mapeo entity_type → path template
- `rule_extensions`: lista de paths a rules markdown

Ver `docs/primitives/memory-loop.md` para el schema completo.
