# Process pipeline

Augmenta notas crudas. Modos `full | light | lint`.

## Manifest schema

```yaml
adapter_name: <kebab-case>
note_type: <snake_case>
applies_when:
  source_dir: <relative-path>
  matches_pattern: ["*.pdf", "*.md", ...]
llm: sonnet | haiku | opus
mode_default: full | light
output_schema:
  required: { <field>: <type>, ... }
  optional: { <field>: <type>, ... }
triple_vocabulary: [<relation>, ...]
tag_axes:
  - { axis: <name>, format: "<axis>/<slug>", required: true | false, min: <int> }
destination_path: "<path-template-with-{frontmatter-fields}>"
qa_triggers:
  - { name: <name>, condition: "<expression>" }
context_injectors:
  - { name: <name>, query: "<query-expression>" }
transform_hook: ./transform.py            # optional
```

Ver [Plan 3](../superpowers/plans/2026-05-16-plan-3-process-pipeline.md).
