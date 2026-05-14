# Bio mensual auto-update — notas operativas

Output de Fase 5 de Rufino. Genera un **snapshot bio narrativa** mensual derivado de `perfil.md` + actividad real del vault del mes anterior. Es un mini-CV / about-me que Val puede copy-paste a:

- LinkedIn (About / Headline).
- Intro a alguien nuevo ("¿quién sos? mandame algo").
- README de un repo propio.
- Sección "About" de cualquier sitio personal.

**No reemplaza `perfil.md`.** Esa nota es source-of-truth manual y se mantiene a mano. El snapshot es derivado, descartable, regenerable.

## Schedule

- **Cron**: día 1 de cada mes a las **06:00** local.
- **Plist**: `~/Library/LaunchAgents/com.user.rufino-bio-monthly.plist` (template en `system/launchd/com.user.rufino-bio-monthly.plist`).
- **Target del mes**: el mes anterior. Cuando corre el 1 de junio, regenera la bio del mes de mayo (`2026-05.md`).
- **Output**: `${RUFINO_VAULT_PATH}/general/bio/YYYY-MM.md`.

El path es `general/bio/` en la raíz del vault (no `rufino/general/bio/`) — el footer del archivo apunta a `[[../../perfil]]` para resolver al `perfil.md` de la raíz desde 2 niveles arriba.

## Override manual

Para regenerar la bio de un mes específico (debugging, rerun, mes pasado):

```bash
RUFINO_BIO_FORCE_MONTH=2026-04 bash ~/.claude/scripts/rufino-bio-monthly.sh
```

El archivo `general/bio/2026-04.md` se sobreescribe en cada corrida — es idempotente. La última corrida es la canónica.

Para dry-run rápido del mes actual (mirar qué saldría sin esperar al cron):

```bash
RUFINO_BIO_FORCE_MONTH=$(date +%Y-%m) bash ~/.claude/scripts/rufino-bio-monthly.sh
tail -30 ~/.claude/logs/rufino/rufino-bio-monthly.log
cat "$RUFINO_VAULT_PATH/general/bio/$(date +%Y-%m).md"
```

## Cómo Val usa el output

Ejemplos de uso concreto del archivo `general/bio/YYYY-MM.md`:

1. **LinkedIn**: copiar los párrafos 1, 2 y 5 → About section. Refresh mensual sin tener que reescribir.
2. **Cold intro**: "che, mandame un par de líneas sobre vos" → mandar los primeros 2 párrafos.
3. **README de proyecto propio**: párrafo 1 + párrafo 5 (stack) como sección "About the author".
4. **Bio para charla / podcast**: usar entero como base, editar tono según audiencia.
5. **Auto-revisión**: leer la bio mensual sirve como "espejo" de cómo se ve Val desde afuera con la data real del mes — ayuda a detectar drift entre lo que dice perfil.md y lo que realmente está haciendo.

## Estructura fija del output

5 párrafos + frontmatter + footer:

1. **Identidad / rol**: nombre, edad, ubicación, roles actuales (TELUS APA + Umbru), background.
2. **Proyectos activos del mes**: lista de proyectos con cantidad de facts del mes por proyecto.
3. **Intereses / consumo cultural del mes**: música (top artistas Spotify/YouTube), gaming, viajes — solo si hay evidencia real del mes.
4. **Highlights del mes**: 2-3 cosas concretas derivadas de sesiones / decisiones / aprendizajes nuevos.
5. **Stack técnico**: lenguajes + tools + el setup de AI-assisted dev.

El frontmatter incluye `month: YYYY-MM` para que el dashboard / queries puedan filtrar por mes.

## Inputs del prompt

El wrapper exporta estos env vars al prompt vía `envsubst`:

| Var | Ejemplo |
|-----|---------|
| `RUFINO_VAULT_PATH` | `/Users/val/Files/vaultlentino` |
| `RUFINO_DISPLAY_NAME` | `Val` |
| `RUFINO_BIO_MONTH` | `2026-04` |
| `RUFINO_BIO_MONTH_START` | `2026-04-01` |
| `RUFINO_BIO_MONTH_END` | `2026-04-30` |
| `RUFINO_BIO_OUTPUT` | `/Users/val/Files/vaultlentino/general/bio/2026-04.md` |

## Cómo Claude cuenta facts del mes

Recorre cada `<source>/facts/` directorio (github, calendar, spotify, screentime, browsing, youtube, gdrive, whatsapp, applehealth, elberr). Para cada `.md`:
- Lee el frontmatter.
- Considera el fact "del mes" si `first_seen` ∈ `[MONTH_START, MONTH_END]` (o `created` si no hay `first_seen`).
- Mantiene contador por source + top 5 facts más recientes por source (para textura concreta — top tracks, top channels, eventos calendar).

Para atribuir facts a proyectos: mira tags `proyecto/<slug>` o `tema/<slug>` matcheando contra la lista de proyectos activos de `perfil.md`.

## Edge cases

- **Mes sin facts (onboarding fresh)**: la bio se genera igual basándose en `perfil.md` + overviews; el párrafo de proyectos omite los números y queda cualitativo.
- **Source recién agregada / sin data**: si una source tiene 0 facts en el mes, no se menciona.
- **Conflicto con perfil.md**: el prompt instruye a NO contradecir lo declarado en `perfil.md`. Si la data del mes parece contradictoria (ej: perfil dice "vivo en BA" pero hay 30 eventos en Madrid), prima `perfil.md`. Los facts son textura, no fuente autoritativa de identidad.
- **Privacidad**: el prompt explícitamente excluye detalles puntuales sobre sustancias / contactos de delivery / situaciones íntimas — categorías generales OK ("uso recreativo", "festivales electrónicos") si están en el perfil; específicos no van a la bio.

## Logging

Cada corrida appendea una línea a `${RUFINO_VAULT_PATH}/_meta/log.md`:

```
[YYYY-MM-DD HH:MM:SS] bio-monthly | mes=YYYY-MM facts_total=N proyectos_con_actividad=M highlights=K
```

Log completo de la corrida en `~/.claude/logs/rufino/rufino-bio-monthly.log` (rotación manual si crece — no rotación automática implementada).

## Locking

Lock file: `${RUFINO_VAULT_PATH}/_meta/.bio-monthly.lock`. Stale-lock-aware: si el PID del lock no responde a `kill -0`, se considera huérfano y se reemplaza. Patrón estándar de la familia `rufino-ingest-*`.

## Por qué corre a las 06:00 (y no 09:00 como dice el spec original)

El spec de Fase 5 sugirió 09:00 pero el setup definitivo lo movió a **06:00** para:
- Quedar antes de que Val abra la laptop (típicamente 9-10 am).
- Evitar overlap con el cron de `gdrive` que también corre día 1 (a las 05:00 — termina con margen antes de las 06:00).
- Que el resto de los outputs de Fase 5 puedan asumir que `general/bio/<YYYY-MM>.md` ya existe a las 6 am del día 1.

## Relación con otros outputs de Fase 5

- **Weekly digest** (viernes 18:00) — semanal, cubre 7 días, narrativo.
- **Bio mensual** (este) — día 1 06:00, snapshot del mes que acaba de cerrar.
- **Year in review** (30 dic 13:00) — retrospectiva narrativa larga del año entero.

Los 3 son outputs derivados que comparten patrón (bash + claude -p + envsubst) pero tocan paths disjuntos en el vault (`digests/`, `bio/`, `year-in-review/`).

## TODO / futuras mejoras

- Email opcional del snapshot (Fase 5 spec lo contempla pero está fuera del scope inicial de este script — agregalo después si Val lo pide).
- Diff vs bio del mes anterior: mostrar al final del archivo qué cambió respecto del snapshot previo (proyectos nuevos, intereses que aparecieron / desaparecieron).
- Versión en inglés para LinkedIn internacional — duplicate prompt con flag de idioma.
