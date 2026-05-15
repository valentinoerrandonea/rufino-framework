# Fase 5 — Outputs automáticos de Rufino

**Status:** approved (2026-05-13)
**Refines:** `vaultlentino/proyectos/rufino/rufino-core/decisionRufinoExpansionPlanFases.md`

## Contexto

Rufino tiene shipped las Fases 1-4: ingestas locales, ingestas con OAuth (con setup pendiente), procesamiento cross-source con embeddings y person resolver, MCP `ask-rufino`. La Fase 5 cierra el loop generando outputs automáticos a partir de toda esa data: resúmenes que Val recibe sin tener que ir a buscarlos.

Tres outputs, todos con email a `valentinoerrandonea2002@gmail.com`:

- **Weekly digest** — viernes 18:00, cubre últimos 7 días.
- **Bio mensual** — día 1 del mes 09:00, regenera `perfil.md`.
- **Año en revisión** — 30 dic 13:00, retrospectiva narrativa del año.

Patrón conocido: script bash que recolecta data, `envsubst` un prompt, `claude -p` lo procesa, escribe al vault, manda email.

## Decisiones tomadas

| Decisión | Elección |
|---|---|
| Scope spec | 1 spec único para foundation + 3 outputs |
| Estilo digest | Narrativo + datos crudos (header narrativo + secciones por fuente) |
| Fuentes digest | GitHub, Calendar, Screen Time, Browsing (facts) + notas vault (sesiones/decisiones/aprendizajes) + pendientes nuevos + conceptos promovidos. **Sin** personas top. |
| Ventana digest | Sábado pasado 00:00 → viernes 18:00 (7 días), Week ID = ISO week del viernes |
| Idempotencia digest | Sobreescribe `.md` en reruns, NO re-manda email (flag `email_sent` en frontmatter) |
| Formato email | Markdown → HTML (parser regex stdlib-only, sin deps externas) |
| Bio destino | Snapshot `rufino/general/bio/YYYY-MM.md` + pisa `perfil.md` con backup previo |
| Bio email | Sí, HTML |
| Año scope | Retrospectiva narrativa larga (1500-3000 palabras) + secciones por dominio |
| Año email | Sí, HTML |
| Cuenta email | val → val (`valentinoerrandonea2002@gmail.com`) |
| Auth Gmail | App password en macOS Keychain (`rufino-gmail-app-password`) |

## Arquitectura

Mismo patrón que la familia `rufino-ingest-*`: bash orquesta, `claude -p` genera contenido, archivos van al vault.

```
~/.claude/scripts/
├── lib/
│   └── rufino-send-email.py              # NUEVO — helper SMTP + MD→HTML
├── setup-gmail-auth.sh                    # NUEVO — Keychain setup interactivo
├── rufino-output-weekly-digest.sh         # NUEVO
├── rufino-output-bio-update.sh            # NUEVO
└── rufino-output-year-in-review.sh        # NUEVO

~/.claude/prompts/
├── rufino-output-weekly-digest.md         # NUEVO
├── rufino-output-bio-update.md            # NUEVO
└── rufino-output-year-in-review.md        # NUEVO

~/Library/LaunchAgents/
├── com.user.rufino-output-weekly-digest.plist     # NUEVO — Fri 18:00
├── com.user.rufino-output-bio-update.plist        # NUEVO — day 1 09:00
└── com.user.rufino-output-year-in-review.plist    # NUEVO — Dec 30 13:00

# Y bajo el repo `~/Files/rufino/`:
claude/scripts/lib/rufino-send-email.py
claude/scripts/setup-gmail-auth.sh
claude/scripts/rufino-output-{weekly-digest,bio-update,year-in-review}.sh
claude/prompts/rufino-output-{weekly-digest,bio-update,year-in-review}.md
system/launchd/com.user.rufino-output-{weekly-digest,bio-update,year-in-review}.plist
docs/output-notes.md                       # NUEVO — doc de operación de los 3 outputs
```

Vault paths (creados automáticamente si no existen):

```
${VAULT}/rufino/general/digests/YYYY-WW.md
${VAULT}/rufino/general/bio/YYYY-MM.md
${VAULT}/rufino/general/bio/YYYY-MM-perfil-backup.md
${VAULT}/rufino/general/year-in-review/YYYY.md
```

## Foundation

### `setup-gmail-auth.sh` (interactivo, one-time)

1. Validar que estamos en macOS (`/usr/bin/security` existe).
2. Pedir email account (default sugerido: `valentinoerrandonea2002@gmail.com`).
3. Pedir app password (read -s, 16 chars). Validar longitud.
4. Guardar en Keychain:
   ```
   security add-generic-password \
     -a "$ACCOUNT" \
     -s "rufino-gmail-app-password" \
     -w "$APP_PASSWORD" \
     -U
   ```
   `-U` = update if exists.
5. Test send opcional: envía un email "Rufino — setup OK" usando el helper. Si responde 0, success; si no, sugerir verificar app password en `myaccount.google.com/apppasswords`.

### `lib/rufino-send-email.py` (helper SMTP)

Python 3 stdlib-only (sin `pip install`). Resuelve estos requisitos:

- Lee credenciales del Keychain:
  - Account: el `-a` guardado (`security find-generic-password -s rufino-gmail-app-password | grep acct`).
  - Password: `security find-generic-password -s rufino-gmail-app-password -w`.
- CLI:
  ```
  rufino-send-email.py \
    --subject "Rufino — Semana 2026-W20" \
    --markdown-file /path/to/digest.md \
    [--to other@example.com]   # default: same account
  ```
- Convierte markdown → HTML con regex sobre el body:
  - Headers `# / ## / ###` → `<h1>/<h2>/<h3>`.
  - Listas `- item` → `<ul><li>`.
  - Listas numeradas `1. item` → `<ol><li>`.
  - `**bold**` → `<strong>`.
  - `_italic_` → `<em>`.
  - Inline code `` `x` `` → `<code>`.
  - Fenced ``` ``` → `<pre><code>`.
  - Wikilinks `[[slug|alias]]` y `[[slug]]` → `<code>slug</code>` (no son links navegables fuera del vault, mostramos como código).
  - Párrafos: bloques separados por blank line → `<p>`.
  - Frontmatter YAML (entre `---` al inicio): se omite del HTML pero se inspecciona para extraer `email_sent`.
- Envío:
  - SSL a `smtp.gmail.com:465` con `smtplib.SMTP_SSL`.
  - `MIMEMultipart('alternative')` con plaintext (el .md original) + HTML.
  - From = account de Keychain. To = `--to` o mismo account.
- Exit codes: 0 OK, 1 con mensaje al stderr en cualquier fallo (auth, conexión, encoding).

## Output 1 — Weekly digest

### Cron

LaunchAgent `com.user.rufino-output-weekly-digest.plist`:

```xml
<key>StartCalendarInterval</key>
<dict>
  <key>Weekday</key><integer>5</integer>  <!-- Friday -->
  <key>Hour</key><integer>18</integer>
  <key>Minute</key><integer>0</integer>
</dict>
```

### `rufino-output-weekly-digest.sh`

```
set -euo pipefail

# Vars
VAULT="${RUFINO_VAULT_PATH:?}"
WEEK_END="${RUFINO_OUTPUT_FORCE_DATE:-$(date +%Y-%m-%d)}"   # default: today (viernes)
WEEK_START="$(date -j -v-6d -f %Y-%m-%d "$WEEK_END" +%Y-%m-%d)"  # 6 días antes = sábado
ISO_WEEK="$(date -j -f %Y-%m-%d "$WEEK_END" +%G-W%V)"
OUTPUT="$VAULT/rufino/general/digests/${ISO_WEEK}.md"
LOG="$HOME/.claude/logs/rufino/rufino-output-weekly-digest.log"
LOCK="$VAULT/_meta/.output-weekly-digest.lock"

# Locking (mismo patrón que ingest)
# ... [stale-lock-aware como rufino-ingest-github.sh:26-35]

# Determinar si email_sent en run anterior (idempotencia)
EMAIL_ALREADY_SENT=false
if [[ -f "$OUTPUT" ]]; then
  if grep -q "^email_sent: true" "$OUTPUT"; then
    EMAIL_ALREADY_SENT=true
  fi
fi

# Recolectar data en JSON temp
DATA_FILE="$(mktemp -t rufino-weekly-digest.XXXX.json)"
trap 'rm -f "$DATA_FILE"' EXIT

# Facts de la ventana
jq -n \
  --arg start "${WEEK_START}T00:00:00" \
  --arg end "${WEEK_END}T18:00:00" \
  --arg iso "$ISO_WEEK" \
  '{ window: { start: $start, end: $end }, iso_week: $iso, facts: [], notes: [], pendientes: [], conceptos: [] }' \
  > "$DATA_FILE"

# Loop por sources con facts/, extrayendo frontmatter `created` con awk o yq
# y filtrando por ventana. Cada match se acumula como objeto en `.facts`.
for SRC in github calendar screentime browsing; do
  if [[ -d "$VAULT/$SRC/facts" ]]; then
    : # implementación detallada en el plan
  fi
done

# Notas modificadas en ventana — find -newermt $WEEK_START -not -newermt $WEEK_END
# sobre sesiones/, proyectos/*/decisiones/, proyectos/*/aprendizajes/.

# Pendientes nuevos: diff _pendientes.md vs hace 7 días via git
# (vault tiene obsidian-git auto-commit cada hora; git -C $VAULT log --since="7 days ago" -p).

# Conceptos: archivos en conceptos/ con mtime en ventana.

# Invocar claude -p
RUFINO_DISPLAY_NAME="${RUFINO_DISPLAY_NAME:-Val}"
export RUFINO_VAULT_PATH RUFINO_DISPLAY_NAME
export RUFINO_DIGEST_DATA_FILE="$DATA_FILE"
export RUFINO_DIGEST_OUTPUT="$OUTPUT"
export RUFINO_DIGEST_ISO_WEEK="$ISO_WEEK"
export RUFINO_DIGEST_WINDOW="$WEEK_START → $WEEK_END"

PROMPT=$(envsubst '${RUFINO_VAULT_PATH} ${RUFINO_DISPLAY_NAME} ${RUFINO_DIGEST_DATA_FILE} ${RUFINO_DIGEST_OUTPUT} ${RUFINO_DIGEST_ISO_WEEK} ${RUFINO_DIGEST_WINDOW}' \
         < "$HOME/.claude/prompts/rufino-output-weekly-digest.md")

claude -p "$PROMPT" \
  --allowedTools "Read,Write,Edit,Glob,Grep,Bash" \
  --dangerously-skip-permissions \
  --model sonnet \
  >> "$LOG" 2>&1

# Preservar / actualizar flag email_sent en frontmatter
# - Si EMAIL_ALREADY_SENT=true (run previo ya envió email): re-aplicar `email_sent: true`
#   al archivo nuevo (Claude lo generó con `email_sent: false`).
# - Si EMAIL_ALREADY_SENT=false: enviar email, y si OK marcar `email_sent: true` ahora.
if [[ "$EMAIL_ALREADY_SENT" == true ]]; then
  sed -i '' 's/^email_sent: false$/email_sent: true/' "$OUTPUT"
elif [[ -f "$OUTPUT" ]]; then
  python3 "$HOME/.claude/scripts/lib/rufino-send-email.py" \
    --subject "Rufino — Semana $ISO_WEEK" \
    --markdown-file "$OUTPUT" \
    >> "$LOG" 2>&1 \
    && sed -i '' 's/^email_sent: false$/email_sent: true/' "$OUTPUT"
fi
```

### Prompt `rufino-output-weekly-digest.md`

Instrucciones a Claude:

- Leer `$RUFINO_DIGEST_DATA_FILE` (JSON con facts + notas + pendientes + conceptos de la semana).
- Leer las notas referenciadas por path (para entender qué pasó).
- Generar markdown con frontmatter:
  ```yaml
  ---
  iso_week: 2026-W20
  window_start: 2026-05-09
  window_end: 2026-05-15
  generated: 2026-05-15T18:00:00
  email_sent: false
  triples:
    - { r: digests, o: weekly }
  tags:
    - tipo/digest
    - tipo/output-rufino
  ---
  ```
- Estructura del cuerpo:
  1. `# Semana YYYY-WW — <titular narrativo corto>` (el titular lo decide Claude según qué pasó esta semana).
  2. Párrafo de overview (3-5 oraciones) narrativo, captura el tono de la semana.
  3. Secciones por fuente con `## GitHub`, `## Calendar`, `## Screen Time`, `## Browsing`, `## Notas nuevas`, `## Pendientes nuevos`, `## Conceptos`. Solo incluir las secciones que tienen contenido.
  4. Bullets dentro de cada sección con los datos crudos.
- Reglas:
  - Wikilinkear personas con `[[slug]]` cuando aparezcan.
  - Wikilinkear notas con `[[nombre-slug]]`.
  - No inventar datos que no estén en el JSON o en las notas leídas.
  - Sí permitido extrapolar narrativa (ej: "fue una semana intensa de código" si hay >40 commits).
- Escribir el archivo a `$RUFINO_DIGEST_OUTPUT` (sobreescribir si existe).

## Output 2 — Bio mensual

### Cron

LaunchAgent `com.user.rufino-output-bio-update.plist`:

```xml
<key>StartCalendarInterval</key>
<dict>
  <key>Day</key><integer>1</integer>
  <key>Hour</key><integer>9</integer>
  <key>Minute</key><integer>0</integer>
</dict>
```

### `rufino-output-bio-update.sh`

Flujo:

1. `MONTH_ID=$(date +%Y-%m)` (o `RUFINO_OUTPUT_FORCE_DATE` para regenerar pasados).
2. Lock + log.
3. Verificar idempotencia: si `bio/${MONTH_ID}.md` existe con `email_sent: true`, no re-emailear pero sí permitir regenerar archivo.
4. **Backup del perfil actual** antes de tocarlo:
   ```bash
   cp "$VAULT/perfil.md" "$VAULT/rufino/general/bio/${MONTH_ID}-perfil-backup.md"
   ```
5. Recolectar data básica en JSON temp:
   - Path del perfil actual.
   - Paths de `experienciaLaboral.md`, `documentosCarrera.md`, `stack.md`.
   - Paths de `proyectos/*/overview.md` con `status` distinto de `archivado`.
   - Paths de decisiones del último mes.
   - Stats agregadas de facts del último mes (top github repos, top calendar attendees, top apps screentime).
6. `claude -p` con prompt `rufino-output-bio-update.md`:
   - Lee perfil actual, experiencia, stack, proyectos, decisiones.
   - Regenera el perfil completo manteniendo el tono y estructura existente, actualizando lo que cambió.
   - Escribe a `$VAULT/rufino/general/bio/${MONTH_ID}.md` (snapshot).
   - Escribe **el mismo contenido** a `$VAULT/perfil.md` (versión viva).
7. Email HTML del snapshot si email no fue enviado este mes.

### Prompt `rufino-output-bio-update.md`

- Lee perfil actual + experiencia + stack + proyectos + decisiones del mes.
- Genera nueva versión del perfil (mantener estructura/secciones existentes, actualizar contenido).
- Frontmatter del snapshot:
  ```yaml
  ---
  month: 2026-06
  generated: 2026-06-01T09:00:00
  email_sent: false
  triples:
    - { r: snapshots, o: perfil }
  tags:
    - tipo/bio
    - tipo/output-rufino
  ---
  ```
- **Importante**: escribir DOS archivos con el mismo cuerpo — el snapshot mensual y `perfil.md`. El snapshot incluye frontmatter de bio; `perfil.md` mantiene su frontmatter original (no se reemplaza el frontmatter, solo el body).

## Output 3 — Año en revisión

### Cron

LaunchAgent `com.user.rufino-output-year-in-review.plist`:

```xml
<key>StartCalendarInterval</key>
<dict>
  <key>Month</key><integer>12</integer>
  <key>Day</key><integer>30</integer>
  <key>Hour</key><integer>13</integer>
  <key>Minute</key><integer>0</integer>
</dict>
```

### `rufino-output-year-in-review.sh`

Flujo:

1. `YEAR_ID=$(date +%Y)` (o env var override).
2. Lock + log.
3. Idempotencia: email solo primera vez del año.
4. Recolectar paths en JSON (no contenido — el volumen sería excesivo):
   - Todos los facts del año: `find $VAULT/{github,calendar,screentime,browsing,spotify,whatsapp,gdrive,youtube}/facts -name "*.md" -newermt "${YEAR_ID}-01-01" -not -newermt "$((YEAR_ID+1))-01-01"`.
   - Todos los weekly digests del año: `$VAULT/rufino/general/digests/${YEAR_ID}-W*.md` (espera ~50).
   - Las 12 bios mensuales: `$VAULT/rufino/general/bio/${YEAR_ID}-*.md`.
   - Decisiones del año, aprendizajes del año.
5. `claude -p` con prompt `rufino-output-year-in-review.md`. Modelo: `sonnet` (subir a `opus` si la calidad no alcanza).
6. Email HTML.

### Prompt `rufino-output-year-in-review.md`

- Lee los 50 weekly digests del año en orden + las 12 bios + decisiones/aprendizajes destacados.
- Genera retrospectiva narrativa de 1500-3000 palabras con:
  1. Apertura narrativa larga (3-5 párrafos) sobre el año.
  2. Secciones por dominio:
     - `## Trabajo` (Umbru, otros clientes según el año).
     - `## Proyectos personales` (Rufino, Elberr, etc.).
     - `## Decisiones que marcaron el año` (top 5-10).
     - `## Aprendizajes` (recurrentes / más citados).
     - `## Gente` (top personas mencionadas, qué pasó con cada una).
     - `## Hábitos / consumo` (música si Spotify activo, lecturas, screentime trends, etc.).
     - `## Hitos del año` (events grandes).
  3. Cierre.
- Frontmatter:
  ```yaml
  ---
  year: 2026
  generated: 2026-12-30T13:00:00
  email_sent: false
  triples:
    - { r: retrospective, o: year }
  tags:
    - tipo/year-in-review
    - tipo/output-rufino
  ---
  ```

## Operational concerns

Aplica a los 3 outputs:

| Concern | Implementación |
|---|---|
| Init de carpetas | Cada script: `mkdir -p ${VAULT}/rufino/general/{digests,bio,year-in-review}` al arranque |
| Locking | `${VAULT}/_meta/.output-<name>.lock` con PID, stale-lock check con `kill -0` |
| Logging | `~/.claude/logs/rufino/rufino-output-<name>.log` |
| Failure mode (claude falla) | Exit 1 con error claro al log; LaunchAgent re-trigea en el próximo cron natural |
| Failure mode (email falla, archivo OK) | Log warning, `email_sent` queda en `false`, rerun manual con `--resend` flag (a definir en plan) |
| Backfill / regenerar pasado | Env var `RUFINO_OUTPUT_FORCE_DATE=YYYY-MM-DD` para digest, `RUFINO_OUTPUT_FORCE_MONTH=YYYY-MM` para bio, `RUFINO_OUTPUT_FORCE_YEAR=YYYY` para year-in-review |
| Claude allowedTools | `Read,Write,Edit,Glob,Grep,Bash` |
| Modelo | `sonnet` para los 3 (arrancamos así, subimos a `opus` si calidad no alcanza en year-in-review) |
| Permisos plist | `EnvironmentVariables` incluye `RUFINO_VAULT_PATH`, `RUFINO_DISPLAY_NAME`, `PATH` |

## Plan de implementación (alto nivel)

Orden secuencial (cada paso es testeable antes de seguir):

1. **Foundation**: `setup-gmail-auth.sh` + `lib/rufino-send-email.py`. Test: setup + envío de email "test" a sí mismo.
2. **Weekly digest** (sub-output más complejo, valida el patrón completo): script + prompt + plist + dry run con `RUFINO_OUTPUT_FORCE_DATE` apuntando a una semana pasada con data conocida.
3. **Bio mensual**: script + prompt + plist + dry run regenerando un mes pasado.
4. **Año en revisión**: script + prompt + plist + dry run para un año pasado.
5. **Doc**: `docs/output-notes.md` con setup, troubleshooting, cómo regenerar.
6. **Actualizar plan en vault**: marcar Fase 5 como ✅ shipped en `decisionRufinoExpansionPlanFases.md`, agregar los 3 nuevos LaunchAgents al inventario.

## Out of scope (YAGNI)

- **Personas top de la semana** — descartado por Val en pregunta 3.
- **Diff visual entre bios mensuales** — los snapshots dan audit trail; no hace falta diff renderizado.
- **Email a destinatarios externos** — solo val → val por ahora.
- **Modo coaching / detección de patrones / mood tracker** — explícitamente NO en el plan original (sección E del doc de fases).
- **Re-mandar email en reruns** — descartado en pregunta 5.
- **Linux support para los plists** — out of scope (el README de Rufino tiene un patrón para crontab en Linux; eventual replicar pero no ahora).
- **Numeración de revisiones (v1/v2/v3)** — descartado en pregunta 5.

## Open questions (decisión técnica diferida, NO bloquea implementación)

| Q | Decisión actual | Trigger para revisar |
|---|---|---|
| ¿Año en revisión con `sonnet` u `opus`? | `sonnet` | Si el primer 30-dic la calidad/coherencia no alcanza, upgrade a `opus`. |
| ¿Bio mensual incluye facts agregados del mes o solo lee vault? | Sólo lee perfil + experiencia + proyectos + decisiones | Si la bio se siente desactualizada con la realidad de la actividad, agregar facts agregados. |
| ¿`obsidian-git` auto-commit interfiere con escritura concurrente al vault? | Asumido OK (las ingestas ya funcionan así desde hace meses) | Si hay conflictos visibles, agregar wait/retry en el writer. |
| ¿`HTML→email` con regex stdlib es suficiente para el rendering en Gmail? | Sí (mínimo viable) | Si el email luce roto en mobile, considerar `pandoc` o `markdown` lib (requiere `pip install`). |

## Referencias

- `vaultlentino/proyectos/rufino/rufino-core/decisionRufinoExpansionPlanFases.md` — plan de fases (Fase 5 marcada como ⏸ pending pre-implementación).
- `rufino/claude/scripts/rufino-ingest-github.sh` — patrón de script ingest (locking, claude -p, envsubst).
- `rufino/docs/schema-fact-externo.md` — schema de facts (no se emiten facts en outputs, pero el frontmatter de los outputs sigue convención consistente).
- `rufino/README.md` — instalación, troubleshooting, estructura.
