# Año en revisión — notas

Retrospectiva anual narrativa, tipo "Spotify Wrapped textual". Corre cada **30 de diciembre a las 13:00** y produce un documento largo sintetizando todo el año del vault.

## Cron

```
Month = 12
Day   = 30
Hour  = 13
Minute = 0
```

Launchd plist: `system/launchd/com.user.rufino-year-review.plist`.
Wrapper: `claude/scripts/rufino-year-review.sh`.
Prompt: `claude/prompts/rufino-year-review.md`.

El cron es **anual** — corre 1 sola vez al año. Si Val quiere ver "año hasta acá" en cualquier momento, puede correrlo manual con el override (ver abajo).

## Output

```
${RUFINO_VAULT_PATH}/general/year-in-review/<YYYY>.md
```

Un archivo por año. **Regenerable**: cada corrida sobreescribe el archivo del año target. El frontmatter preserva el `created:` original si la nota ya existía y mueve sólo `updated:`.

## Frontmatter

```yaml
---
tags:
  - proyecto/val
  - tipo/year-in-review
  - source/rufino
created: YYYY-12-30      # primera generación
updated: YYYY-MM-DD      # última regeneración
year: YYYY
coverage: full|partial   # partial si la corrida fue antes del 30 dic
---
```

## Secciones del documento

1. **Resumen** — 3-5 párrafos narrativos.
2. **Proyectos** — uno por proyecto activo (>=3 notas en el año).
3. **Personas** — narrativa de relaciones del año.
4. **Música y consumo cultural** — top artistas Spotify + canales YouTube.
5. **Viajes** — destinos con evidencia en el vault (calendar/browsing/sesiones).
6. **Decisiones grandes** — bullets de `decision*.md` del año con wikilinks.
7. **Aprendizajes** — bullets de `aprendizaje*.md` del año con wikilinks.
8. **Stats numéricos** — tabla con counts (facts por source, sesiones, decisiones, aprendizajes, personas).
9. **Pendientes completados** — del `_pendientes.md`.
10. **Mirando YYYY+1** — 1-2 párrafos de proyección.

## Override manual

### Correr el año actual ahora mismo

```bash
export RUFINO_VAULT_PATH=/path/al/vault
bash ~/.claude/scripts/rufino-year-review.sh
```

Sin override, el script toma `date +%Y` como año target — así que si lo corrés en mayo, te da "2026 hasta acá" con `coverage: partial`.

### Regenerar un año específico

```bash
RUFINO_YEAR_FORCE=2025 bash ~/.claude/scripts/rufino-year-review.sh
```

Útil para regenerar años pasados si el prompt evoluciona, o para "ponerse al día" cargando años previos al deploy del cron.

### Tip — año hasta acá en cualquier momento

Val puede correrlo cada vez que quiera ver un snapshot del año en curso. El doc se marca `coverage: partial` y la sección "Resumen" abre con "Hasta `<fecha>`, el año viene siendo...". No interfiere con la corrida automática del 30 dic — el cron sobreescribirá con la versión `full` al cierre.

## Stats pre-computados

El wrapper calcula counts antes de invocar a Claude (vía `grep -lE` por `first_seen:` o `created:` con el año target) y los pasa como env vars al prompt:

| Variable | Cuenta |
|---|---|
| `RUFINO_STATS_FACTS_GITHUB` | facts en `github/facts/` del año |
| `RUFINO_STATS_FACTS_CALENDAR` | facts en `calendar/facts/` del año |
| `RUFINO_STATS_FACTS_SPOTIFY` | facts en `spotify/facts/` del año |
| `RUFINO_STATS_FACTS_YOUTUBE` | facts en `youtube/facts/` del año |
| `RUFINO_STATS_FACTS_WHATSAPP` | facts en `whatsapp/facts/` del año |
| `RUFINO_STATS_FACTS_BROWSING` | facts en `browsing/facts/` del año |
| `RUFINO_STATS_FACTS_SCREENTIME` | facts en `screentime/facts/` del año |
| `RUFINO_STATS_FACTS_APPLEHEALTH` | facts en `applehealth/facts/` del año |
| `RUFINO_STATS_FACTS_GDRIVE` | facts en `gdrive/facts/` del año |
| `RUFINO_STATS_SESIONES` | archivos `sesiones/<YYYY>-*.md` |
| `RUFINO_STATS_DECISIONES` | `decision*.md` con frontmatter del año |
| `RUFINO_STATS_APRENDIZAJES` | `aprendizaje*.md` con frontmatter del año |
| `RUFINO_STATS_PERSONAS_TOTAL` | total acumulado en `rufino/_people/` |

Claude puede refinar (ej. abrir summaries de Spotify y agregarles `total_tracks` para un agregado anual) pero los counts base evitan inventos.

## Cobertura parcial vs completa

```bash
TODAY=$(date +%Y-%m-%d)
CUTOFF=${TARGET_YEAR}-12-30
if [ "$TODAY" \< "$CUTOFF" ]; then COVERAGE=partial; else COVERAGE=full; fi
```

- **`full`** → cron del 30 dic o run manual a fin de año. El doc cierra el año.
- **`partial`** → run manual durante el año. El doc abre acknowledging que falta cubrir lo que resta.

## Locking

Lock file en `${RUFINO_VAULT_PATH}/_meta/.year-review.lock`. Stale-lock-aware (chequea si el PID sigue vivo).

## Reglas críticas (no se viola)

- **Solo escribe** `${RUFINO_YEAR_OUTPUT_FILE}`. NO toca facts, decisiones, sesiones, conceptos, `_index`, `_people`, ni nada más del vault. Es una vista derivada.
- **Fidelidad > fluidez**: si una sección no tiene data, lo dice. No fabrica destinos de viaje, no inventa relaciones.
- **Idempotente**: regenerable N veces sin acumular duplicados.

## Logging

```
~/.claude/logs/rufino/rufino-year-review.log
```

Cada corrida loguea: target year, stats pre-computados, coverage, output path.

## Validación inicial

Dry-run (mayo 2026) con `RUFINO_VAULT_PATH=~/Files/vaultlentino bash claude/scripts/rufino-year-review.sh`. Va a generar `general/year-in-review/2026.md` con `coverage: partial` y data acumulada hasta hoy. Validá:

1. Archivo creado en el path correcto.
2. Frontmatter con `year: 2026`, `coverage: partial`.
3. Todas las H2 presentes.
4. Counts de la tabla matchean los stats del log.
5. Secciones sin data dicen "sin registros" en vez de inventar.

## Instalación del cron

```bash
LABEL="com.user.rufino-year-review"
sed "s|__HOME__|$HOME|g" ~/Files/rufino/system/launchd/${LABEL}.plist > ~/Library/LaunchAgents/${LABEL}.plist
launchctl load ~/Library/LaunchAgents/${LABEL}.plist
```

Editar `RUFINO_VAULT_PATH` en el plist instalado antes del load.

## Roadmap

- **Trends multi-año**: cuando haya >=2 años acumulados, agregar sección "Comparado con `<YYYY-1>`" — diff de proyectos, evolución de personas, drift de gustos musicales. Por ahora con un año no aplica.
- **Embeddings-based section**: usar `rufino-search-embeddings.py` para encontrar las notas semánticamente más densas/inusuales del año y citarlas en "highlights".
- **Export a PDF/imagen**: por ahora es markdown puro; si Val quiere algo shareable, podría haber un sub-job que convierta a PDF estilizado (no implementado).
