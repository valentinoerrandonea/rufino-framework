# Pattern: decision_log_with_rationale

## Trigger language
- "decisiones"
- "por qué hicimos X"
- "registro de criterios"
- "ADRs"
- "no quiero olvidarme por qué"

## Entity types típicos
- decision, rationale, alternative

## Combinación de primitives
- Process con triple `supersedes` (decisión nueva reemplaza vieja)
- Lint orphans (decisiones sin contexto)
- Output search facetada

## Casos
- ADRs técnicos
- Decisiones de producto
- Jurisprudencia personal
