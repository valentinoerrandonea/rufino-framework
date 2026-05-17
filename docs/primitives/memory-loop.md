# Memory loop

Integración con conversaciones de Claude Code en curso.

## Adapter shape

Vertical config — ver [docs/adapters/vertical-config.md](../adapters/vertical-config.md).

## Manifest schema

```yaml
adapter_name: <kebab-case>
vertical_name: <slug>
entity_types: [<type>, ...]
note_destinations:
  <type>: "<path-template>"
rule_extensions: [./rules/<vertical>-vocabulary.md, ./rules/<vertical>-conventions.md]
```

Ver [Plan 2](../superpowers/plans/2026-05-16-plan-2-memory-loop.md).
