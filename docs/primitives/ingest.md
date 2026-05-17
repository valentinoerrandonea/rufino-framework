# Ingest engine

Trae data de fuentes externas y la normaliza al vault. Tres `output_mode`:
- `emit_fact`: records atómicos en `<source>/facts/`
- `import_raw`: docs largos al inbox (dispara Process inmediato por default)
- `emit_augmented`: streaming directo a Process — el manifest se acepta y valida, pero el dispatcher inline está **deferido a v1.1** (el adapter no corre todavía).

## Manifest schema

```yaml
adapter_name: <kebab-case>
source_name: <slug>
schedule: "<cron-expression>"
auth: { type: oauth2 | api_key | none, keychain_service: <slug> }
output_mode: emit_fact | import_raw | emit_augmented

# emit_fact-specific:
emits: [<entity_type>, ...]
fact_schema: { <field>: <type>, ... }
destination:
  facts: <path-template>
  raw: <path-template>
dedup_by: <field-name>

# import_raw-specific:
target_inbox: <relative-path>
process_with: <process-adapter-name>
trigger: immediate | defer       # default: immediate

# emit_augmented-specific:
process_inline_with: <process-adapter-name>     # required

# optional (parsed but execution deferred — see worker-adapter.md):
transform_hook: ./transform.py
```

Ver [Plan 4](../superpowers/plans/2026-05-16-plan-4-ingest-engine.md) para el contrato completo + helpers.
