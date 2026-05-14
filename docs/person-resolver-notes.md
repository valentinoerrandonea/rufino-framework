# Cross-source person resolver

Script standalone on-demand (Fase 4) que detecta posibles duplicados en `_people/<slug>.md` con string similarity y genera notas en `questions/` para que Val confirme.

> **NO** mergea nada automáticamente. **NO** depende de embeddings (otro componente paralelo cubre eso).

## Archivos

- `claude/scripts/rufino-person-resolver.py` — implementación.
- `claude/scripts/rufino-person-resolver.sh` — thin wrapper con logging.

## Uso

```bash
export RUFINO_VAULT_PATH=/Users/val/Files/vaultlentino

# Dry-run (no escribe nada):
./claude/scripts/rufino-person-resolver.sh --dry-run

# Run real (crea questions/ si hace falta):
./claude/scripts/rufino-person-resolver.sh

# Threshold custom (default 0.6):
./claude/scripts/rufino-person-resolver.sh --threshold 0.5

# Mostrar top 30 pares (útil para tunear):
./claude/scripts/rufino-person-resolver.sh --dry-run --verbose
```

Val lo lanza manualmente. **No hay LaunchAgent** ni cron.

Log: `${RUFINO_LOG_DIR:-$HOME/.claude/logs/rufino}/rufino-person-resolver.log`.

## Cómo funciona

### 1. Carga

Lee todos los `${RUFINO_VAULT_PATH}/rufino/_people/<slug>.md` (excepto los que empiezan con `_`). Por cada persona extrae:

- `slug` = filename sin `.md`.
- `display_name` = primer `# H1` del body (fallback: slug).
- `sources` = lista del frontmatter (ej `[whatsapp, calendar]`).
- `referenced_in` = cantidad de notas externas que linkean al slug por wikilink (`[[slug]]`, `[[path/slug]]`, `[[slug|alias]]`) o tag (`persona/<slug>`).

### 2. Scoring

Para cada par `(a, b)` calcula:

| Señal | Cómputo | Peso |
|---|---|---|
| `name_levenshtein` | `1 - dist(norm(name_a), norm(name_b)) / max_len` | 0.40 |
| `name_jaccard` | tokens compartidos / tokens unidos (tokens >1 char) | 0.20 |
| `slug_similarity` | máx(prefix bonus, containment, levenshtein) sobre slugs | 0.20 |
| `subset_bonus` | 1 si un nombre es substring del otro o sus tokens son subset, 0 si no | 0.20 |

`norm()` = lowercase + strip de acentos (NFD + filter Mn) + collapse de whitespace.

**Penalización por shared mentions**: si hay una nota fuera de `_people/` que linkea AMBOS slugs, asumimos que Val los está usando juntas → `score *= 0`.

Bandas:

- `HIGH` ≥ 0.85 — match casi seguro.
- `MEDIUM` 0.60–0.85 — posible.
- `LOW` < 0.60 — se descarta (no genera question).

### 3. Output

Por cada par con `score >= threshold`, genera `${RUFINO_VAULT_PATH}/questions/person-resolution-<slug_a>-vs-<slug_b>.md` siguiendo `docs/schema-question.md`. Los slugs van en orden lexicográfico para que el filename sea determinístico.

### 4. Idempotencia

Antes de crear, chequea:

- `questions/person-resolution-<a>-vs-<b>.md`
- `questions/person-resolution-<b>-vs-<a>.md`
- `questions/_archive/<misma cosa>` (ambos órdenes)

Si existe cualquiera, **skip**. Eso preserva las questions creadas manualmente (ej `person-resolution-guillermo-tressols-vs-guille.md` y `person-resolution-martin-errandonea-vs-martin.md`).

## Edge cases y limitaciones

- **Self-references en `_people/<slug>.md`**: el body de un `_people` suele linkear al "posible duplicado" (ej `_people/guillermo-tressols.md` dice "posible identidad con `[[guille]]`"). Esas menciones **no** cuentan como shared, porque son justamente el reporte del problema, no evidencia de que sean distintos. El resolver excluye explícitamente los archivos `_people/<slug>.md` del conteo de `shared_mentions`.
- **Notas-aprendizaje sobre ambigüedad**: si existe una nota tipo `aprendizajeWhatsappGuillermoTressolsAmbiguedad.md` que menciona ambos slugs documentando la duda, va a contar como shared mention y el resolver va a borrar el score. **Es un falso negativo conocido.** Como ya hay question manual para esos casos, no es bloqueante. Si llega a molestar, agregar regex de exclusion sobre paths/títulos que contengan `ambiguedad` o `_processing-log`.
- **Nombres muy distintos con slugs alineados** (ej `guille` / `guillermo-tressols` → display "Guille" / "Guillermo Tressols"): el slug similarity es 1.0 y el subset_bonus es 1.0, pero el name_levenshtein cae a 0.33 y el jaccard a 0 (porque los tokens "guille" y "guillermo" son distintos). Score final: ~0.53, debajo del threshold default. Es **diseño**: el first-cut prefiere falsos negativos a falsos positivos. El componente de embeddings va a captar estos casos por semántica.
- **Frontmatter con listas YAML**: el parser ad-hoc soporta solo el subset usado en `_people/` (scalars + listas `- item`). Si alguna fuente futura agrega anidamiento profundo, hay que cambiar a `PyYAML` o `tomllib`.
- **No usa la lista `sources`** para decidir si son duplicados — solo la incluye como contexto en la question. Personas con el mismo nombre y misma source podrían ser duplicados legítimos (raro en este vault, pero posible).

## Tuning

Los pesos son lineales y suman 1.0. Para mover el threshold sin tocar código, usar `--threshold`. Para experimentar con pesos, editar el dict `WEIGHTS` en el script.

## Próximos pasos (fuera de scope de esta Fase 4)

- Procesador que lee questions con `status: answered`, aplica el merge (re-puntear wikilinks, fusionar frontmatter, archivar la nota), y mueve la question a `_archive/`.
- Integración con el componente de embeddings: si embeddings da una probabilidad ≥ 0.7 pero el string resolver da score < 0.6, generar question combinada con las dos señales.
- Stale detection: si un `_people/<slug>.md` tiene `referenced_in == 0` durante N runs, sugerir archivado.
