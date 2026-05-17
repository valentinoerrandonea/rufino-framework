---
template_name: materia_ambigua
required_context: [apunte_slug, candidate_materias, evidence]
expected_answer: "enum_from(candidate_materias) | 'nueva' | 'ninguna'"
---

# ¿De qué materia es {{ apunte_slug }}?

Encontré candidatos:
{% for c in candidate_materias -%}
- **[[materia-{{ c.slug }}]]** ({{ c.confidence }}% — {{ c.reason }})
{% endfor %}

## Evidencia
{{ evidence }}

## Respondé editando frontmatter
`answer: <slug>` | `answer: nueva` + `nueva_materia: <slug>` | `answer: ninguna`
