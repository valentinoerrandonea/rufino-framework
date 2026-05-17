# Q&A loop

Pipeline de preguntas que solo el user puede resolver.

## API

```python
api.ask_user(template_name, context, adapter_name, adapter_state) → question_slug
api.get_answer(slug) → answer | None
```

Worker poll dispatch:

```bash
rufino qa-poll --vault X --state-dir Y
```

Templates: ver [docs/adapters/question-template.md](../adapters/question-template.md).

Ver [Plan 6](../superpowers/plans/2026-05-16-plan-6-qa-loop.md).
