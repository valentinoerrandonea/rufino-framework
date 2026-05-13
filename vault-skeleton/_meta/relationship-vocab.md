# Vocabulario de relaciones tipadas (triples)

Las relaciones tipadas viven en el frontmatter de cualquier nota como:

```yaml
triples:
  - { r: depends-on, o: decisionSupabaseAuth }
  - { r: led-to, o: aprendizajeRsyncEmbedded }
```

El subject es implícito: la nota cuyo archivo contiene el frontmatter. El object es el id de cualquier otra entidad del vault (nota, persona, proyecto, concepto).

## Relaciones canónicas

| Relación | Significado | Ejemplo |
|---|---|---|
| `depends-on` | El subject necesita al object para funcionar | `decisionPricing depends-on decisionStack` |
| `blocks` | El subject impide / posterga al object | `bugAuth blocks decisionShipBeta` |
| `caused-by` | El subject fue desencadenado por el object | `refactorAPI caused-by aprendizajeBugLatencia` |
| `led-to` | El subject desencadenó al object | `decisionElectron led-to aprendizajeNextStandalone` |
| `references` | El subject menciona al object como source | `aprendizajeX references memoBush1945` |
| `contradicts` | El subject contradice al object | `decisionV2 contradicts decisionV1` |
| `refines` | El subject mejora / precisa al object | `decisionV2 refines decisionV1` |
| `replaces` | El subject reemplaza al object | `decisionMongoDb replaces decisionPostgres` |
| `decided-by` | (sólo decisiones) Quién la tomó | `decisionPricing decided-by alejo` |
| `learned-in` | (sólo aprendizajes) En qué proyecto | `aprendizajeRsync learned-in rufino-dashboard` |

## Reglas

- **No inventar relaciones**: si querés agregar un tipo nuevo, primero edita este doc.
- **Subject implícito**: nunca poner `s:` — es siempre el archivo actual.
- **Object por id, no por path**: `decisionSupabaseAuth`, no `proyectos/umbru/decisiones/decisionSupabaseAuth.md`.
- **Si el id existe en más de un lugar**, el resolver agarra el primer match. El lint pass detecta IDs duplicados.
