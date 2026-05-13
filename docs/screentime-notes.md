# Screen Time ingestor — notas operativas

## TCC (Full Disk Access)

La macOS Knowledge DB (`~/Library/Application Support/Knowledge/knowledgeC.db`) está protegida por TCC. La primera vez que el LaunchAgent corre, va a fallar con `authorization denied`.

**Fix (una sola vez por máquina)**:
1. System Settings → Privacy & Security → Full Disk Access.
2. Click `+` y agregar `/bin/bash` (el binario que invoca el plist).
3. Reload el LaunchAgent:
   ```bash
   launchctl unload ~/Library/LaunchAgents/com.user.rufino-ingest-screentime.plist
   launchctl load   ~/Library/LaunchAgents/com.user.rufino-ingest-screentime.plist
   ```
4. Trigger manual para verificar:
   ```bash
   launchctl start com.user.rufino-ingest-screentime
   tail -f ~/.claude/logs/rufino/rufino-ingest-screentime.log
   ```

El script tiene un TCC probe (`SELECT 1 FROM ZOBJECT LIMIT 1;`) que aborta con mensaje claro si la lectura falla, así no se ejecuta Claude para nada.

## Schema gotchas (knowledgeC.db)

- `ZOBJECT.ZSTARTDATE` y `ZENDDATE` son Mac absolute time: segundos desde `2001-01-01 00:00:00 UTC`. Conversión: `unix_ts = mac_ts + 978307200`.
- `ZSTREAMNAME` tiene `/app/usage` (lo que nos interesa), `/app/intents`, `/app/mediaUsage`. **`/app/inFocus` no existe** en macOS 14+ (al menos no en samples actuales — usá `/app/usage` que sí existe y agrega segundos totales por sesión).
- `ZVALUESTRING` puede ser NULL para algunos rows — los excluimos via `ZENDDATE > ZSTARTDATE` y `COALESCE`.
- La schema cambia entre versiones de macOS; el script asume macOS 14+ (Knowledge DB con la schema actual de ~37 columnas). Si cambia, el script va a fallar limpiamente en la query.

## Frecuencia y target

- Cron: domingos 04:00 (Weekday=0 en launchd).
- Procesa la **semana ISO anterior**: `date -v-7d +%G-W%V`. Domingo a las 04:00 procesa la semana que terminó hace 4 horas (el domingo previo cerró la semana).
- Override manual: `RUFINO_SCREENTIME_FORCE_WEEK=2026-W19 ~/.claude/scripts/rufino-ingest-screentime.sh`.

## Output esperado

Por semana, hasta 6 facts:
- 1 summary: `screentime-summary-<YYYY-WW>` con top-10 agregado.
- 5 app facts: `screentime-app-<bundle-slug>-<YYYY-WW>`, uno por cada app del top-5.

Apps con <5min total se descartan (ruido). Bundles no resueltos al mapping de nombres legibles se loguean en el body del summary.
