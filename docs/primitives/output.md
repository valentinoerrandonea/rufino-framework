# Output dispatcher

Genera derivados del vault: digests, reportes, recomendaciones, alertas.

## Manifest schema

```yaml
adapter_name: <kebab-case>
trigger:
  type: cron | on_event
  expression: "<cron>"                    # if type=cron
  event: <event-name>                     # if type=on_event
  filter: "<expression>"                  # if type=on_event
query:
  - { name: <name>, expression: "<query>" }
template: ./templates/<name>.md
delivery:
  - { channel: file, path: "<path-template>" }
  - { channel: email, to: "<addr>", subject: "<subject>" }
  - { channel: webhook, url: "<url>" }
  - { channel: push, title: "<title>" }
```

Ver [Plan 5](../superpowers/plans/2026-05-16-plan-5-output-dispatcher.md).
