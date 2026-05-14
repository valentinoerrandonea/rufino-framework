# rufino-notes-and-memory

> Sistema personal de memoria asistida por Claude Code + Obsidian. Procesa notas, genera triples tipados, promociona conceptos, extrae pendientes, mantiene índices, te recuerda guardar al vault al cerrar conversaciones.

## Cómo funciona

Dos capas que se combinan:

1. **Obsidian Memory** — Claude lee `perfil.md` y `preferencias.md` de tu vault al inicio de cada conversación, detecta en qué proyecto estás según tu CWD, y crea/actualiza `proyectos/<x>/overview.md` automáticamente. Una skill `/remember` decide la carpeta destino correcta (sesiones, decisiones, aprendizajes) cuando le pedís guardar algo.
2. **Rufino** — Tres crons procesan tu vault: convierten notas crudas en notas enriquecidas con augmentation, generan triples tipados desde wikilinks, promueven conceptos cuando aparecen ≥2 veces, extraen pendientes inline, mantienen índices.

Más un hook que al fin de cada conversación te pregunta si hay algo para guardar al vault.

## Prerrequisitos

- macOS o Linux con bash 3.2+.
- [Claude Code](https://claude.com/claude-code) instalado y autenticado.
- [Obsidian](https://obsidian.md/) instalado con un vault local.
- Plugin **obsidian-git** instalado en Obsidian, configurado para auto-commit cada hora (auto-backup del vault — no se distribuye con este repo).
- `jq` (`brew install jq` en macOS, `apt install jq` en Linux) — usado por el hook.
- `envsubst` (viene con `gettext` — en macOS `brew install gettext`, en Linux suele estar pre-instalado).

## Instalación

### 1. Cloná el repo

```bash
git clone https://github.com/<tu-user>/rufino-notes-and-memory.git ~/rufino-notes-and-memory
cd ~/rufino-notes-and-memory
```

### 2. Seteá tus variables de entorno

Agregá esto a tu `~/.zshenv` (o `~/.bashrc`):

```bash
export RUFINO_VAULT_PATH="/path/absoluto/a/tu/vault"
export RUFINO_DISPLAY_NAME="Tu Nombre"
export RUFINO_LOG_DIR="$HOME/.claude/logs/rufino"  # opcional, este es el default
```

Después: `source ~/.zshenv` (o abrí una shell nueva).

### 3. Copiá la config de Claude a `~/.claude/`

```bash
mkdir -p ~/.claude/{hooks,prompts,rules/common,scripts,commands} ~/.claude/logs/rufino
cp -n claude/hooks/* ~/.claude/hooks/
cp -n claude/prompts/* ~/.claude/prompts/
cp -n claude/rules/common/* ~/.claude/rules/common/
cp -n claude/scripts/* ~/.claude/scripts/
cp -n claude/commands/* ~/.claude/commands/
chmod +x ~/.claude/scripts/rufino-*.sh ~/.claude/hooks/*.sh
```

`cp -n` (no-clobber) no sobrescribe archivos pre-existentes. Si tenés tu propia config en `~/.claude/`, esos archivos sobreviven — resolvé conflictos a mano.

### 4. Editá las reglas y la skill /remember

Abrí los siguientes 3 archivos y reemplazá `$VAULT_PATH` por tu path absoluto y `$DISPLAY_NAME` por tu nombre:

- `~/.claude/rules/common/obsidian-memory.md`
- `~/.claude/rules/common/rufino.md`
- `~/.claude/commands/remember.md`

O con sed (más rápido):

```bash
for f in ~/.claude/rules/common/obsidian-memory.md ~/.claude/rules/common/rufino.md ~/.claude/commands/remember.md; do
  sed -i '' "s|\$VAULT_PATH|$RUFINO_VAULT_PATH|g; s|\$DISPLAY_NAME|$RUFINO_DISPLAY_NAME|g" "$f"
done
```

### 5. Copiá el skeleton al vault

```bash
cp -Rn vault-skeleton/. "$RUFINO_VAULT_PATH/"
```

**Importante:** abrí `$RUFINO_VAULT_PATH/perfil.md` y `$RUFINO_VAULT_PATH/preferencias.md` en tu editor y completalos. Claude los lee al inicio de cada conversación; si están vacíos, no va a tener contexto sobre quién sos ni cómo te gusta trabajar.

### 6. Instalá los crons (macOS / launchd)

Los plists vienen con placeholder `__HOME__` y con `RUFINO_VAULT_PATH` vacío. Reemplazá ambos en bloque y copialos:

```bash
for f in system/launchd/*.plist; do
  sed -e "s|__HOME__|$HOME|g" \
      -e "/<key>RUFINO_VAULT_PATH<\\/key>/{n;s|<string></string>|<string>$RUFINO_VAULT_PATH</string>|;}" \
      "$f" > "$HOME/Library/LaunchAgents/$(basename "$f")"
done
```

(El segundo sed busca la línea `<key>RUFINO_VAULT_PATH</key>` y reemplaza el `<string></string>` inmediatamente después.)

Cargá los servicios:

```bash
launchctl load ~/Library/LaunchAgents/com.user.rufino-cron.plist
launchctl load ~/Library/LaunchAgents/com.user.rufino-light-cron.plist
launchctl load ~/Library/LaunchAgents/com.user.rufino-lint-cron.plist
```

### 6b. Crontab equivalente (Linux)

En Linux con cron tradicional, agregá a tu crontab (`crontab -e`):

```cron
RUFINO_VAULT_PATH=/path/absoluto/a/tu/vault
RUFINO_DISPLAY_NAME=Tu Nombre

0 22 * * * /bin/bash ~/.claude/scripts/rufino-cron.sh
0 2 * * *  /bin/bash ~/.claude/scripts/rufino-light-cron.sh
0 3 * * 0  /bin/bash ~/.claude/scripts/rufino-lint-cron.sh   # Domingo 03:00 — lint es semanal
```

## Verificación post-install

1. **Servicios cargados**:
   ```bash
   launchctl list | grep rufino
   ```
   Expected: 3 servicios `com.user.rufino-*`.

2. **Procesamiento manual de una nota**:
   ```bash
   echo "# Test\n\nNota cualquiera con un [[wikilink]]." > "$RUFINO_VAULT_PATH/rufino/test-$(date +%s).md"
   bash ~/.claude/scripts/rufino-cron.sh
   tail -50 "$RUFINO_LOG_DIR/rufino-cron.log"
   ```
   Expected: el log muestra "Rufino run" y "Rufino done", y la nota se movió a `rufino/<proyecto>/<tipo>/`.

3. **Auto-creación de overview de proyecto**:
   - Abrí Claude Code en un directorio que no sea conocido (un proyecto nuevo).
   - Pedile cualquier tarea.
   - Confirmá que se creó `$RUFINO_VAULT_PATH/proyectos/<x>/overview.md` y que `$RUFINO_VAULT_PATH/_meta/projectPaths.md` registró el path.

4. **Skill /remember**:
   - En una conversación con Claude, decile: "Guardá esta conversación como sesión".
   - Confirmá que se creó `$RUFINO_VAULT_PATH/sesiones/<YYYY-MM-DD-tema>.md`.

## Estructura del repo

```
rufino-notes-and-memory/
├── README.md
├── docs/
│   ├── schema-fact-externo.md   # Schema canónico para ingestors externos
│   └── schema-question.md       # Pipeline questions/ (Rufino pregunta, vos contestás)
├── claude/
│   ├── hooks/obsidianMemoryCheck.sh
│   ├── prompts/rufino-{daily,light-cron,import-plan,process-single,reprocess,lint}.md
│   ├── prompts/rufino-ingest-{github,...}.md
│   ├── rules/common/{obsidian-memory,rufino}.md
│   ├── scripts/rufino-{cron,light-cron,import-plan,process-single,lint-cron}.sh
│   ├── scripts/rufino-ingest-{github,...}.sh
│   └── commands/remember.md
├── vault-skeleton/
│   ├── perfil.md, preferencias.md
│   ├── rufino/, conceptos/, proyectos/, sesiones/, inbox/
│   ├── github/, questions/      # Carpetas para ingestors externos + Q&A
│   ├── _meta/, _templates/, obsidian-config/, seed-notes/
└── system/launchd/com.user.rufino-{cron,light-cron,lint-cron,ingest-github}.plist
```

## Qué hace cada cron

### Crons de procesamiento (siempre activos)

| Cron | Horario | Qué hace |
|---|---|---|
| `rufino-cron` | 22:00 | Procesa notas crudas (`rufino/*.md` raíz): augmentation, tags, triples, mueve a `rufino/<proyecto>/<tipo>/`. |
| `rufino-light-cron` | 02:00 | Catch-up: notas que ya escribiste a mano fuera del flujo crudo. Agrega triples, promociona conceptos, registra personas, extrae pendientes. NO reescribe el cuerpo. |
| `rufino-lint-cron` | Domingo 03:00 (semanal) | Valida invariantes del vault (frontmatter, wikilinks rotos, stale-inbox, etc.) y escribe un reporte JSON en `_meta/`. |

### Ingestors externos (opt-in, ver `docs/schema-fact-externo.md`)

Cada ingestor lee una fuente externa (API o data local), deriva facts atómicos y los escribe en `<source>/facts/<slug>.md` del vault. Los facts comparten el schema canónico documentado en `docs/schema-fact-externo.md` (idempotente, slug determinístico, audit trail en `<source>/raw/`).

| Cron | Horario | Fuente | Qué emite |
|---|---|---|---|
| `rufino-ingest-github` | 06:30 diario | `gh` CLI (GraphQL contributions API + REST events) | Facts de commits (1 por repo/día), PRs, issues, reviews, stars, repos creados, releases. |
| `rufino-ingest-calendar` | 07:00 diario | `~/Library/Group Containers/group.com.apple.calendar/Calendar.sqlitedb` (TCC) | Facts por evento del día anterior, con personas invitadas como tags `persona/<x>`. |
| `rufino-ingest-screentime` | Domingo 04:00 | `~/Library/Application Support/Knowledge/knowledgeC.db` (TCC) | Summary semanal top-10 apps + facts individuales de top-5 con minutos de uso. |
| `rufino-ingest-browsing` | Domingo 03:30 | Zen Browser (`places.sqlite`) + Safari (`History.db`) unificados, copia a tmp | Top dominios de la semana (Zen+Safari sumados) + facts por queries repetidas Google ≥3 veces + clusters de research. Privacy filter aplicado al body, raw conserva todo. |
| `rufino-ingest-spotify` | Domingo 04:30 | Spotify Web API (`/me/player/recently-played`) | Summary semanal + top artists + tracks recurrentes (≥5 plays). |
| `rufino-ingest-gdrive` | Día 1 mensual 05:00 | Google Drive API v3 (changes delta) | Importa docs/PDFs nuevos de "Mi unidad" a `rufino/` raw para que el pipeline normal los procese. Emite summary fact mensual. |
| `rufino-ingest-youtube` | Día 5 mensual 05:30 | Google Takeout export bimestral (consume el ZIP desde Drive) | Summary bimestral + top channels + research clusters de watch history. |
| `rufino-ingest-applehealth` | Día 2 mensual 06:00 | iCloud Drive `RufinoHealth/` (poblada por Apple Shortcut iOS) | Summary mensual + workout types recurrentes + sleep/HR/steps trends. |
| `rufino-ingest-whatsapp` | Domingo 05:00 | WhatsApp Web vía `whatsapp-web.js` (Puppeteer headless, sesión persistida) | Summary semanal + frecuencia por contacto top 10 + topics recurrentes. Privacy filter doble (sin texto literal). |

> **Calendar y Screen Time requieren TCC Full Disk Access** para `/bin/bash` (System Settings → Privacy & Security → Full Disk Access). El primer run del LaunchAgent va a fallar con instrucciones claras en el log si el grant falta.
>
> **Spotify, GDrive, YouTube requieren setup OAuth one-time** antes del primer real run:
> - Spotify: `bash ~/.claude/scripts/setup-spotify-auth.sh` después de registrar `http://127.0.0.1:8765/callback` en el dashboard de la app. Ver `docs/spotify-notes.md`.
> - GDrive: crear proyecto en GCP Console + OAuth client desktop + `bash ~/.claude/scripts/setup-gdrive-auth.sh`. Ver `docs/gdrive-notes.md`.
> - YouTube: configurar export bimestral en `takeout.google.com` (reusa el OAuth de GDrive). Ver `docs/youtube-notes.md` (si existe).

### Capas adicionales sobre los ingestors (Fase 4)

- **Embeddings vault-wide** — `claude/scripts/rufino-build-embeddings.{py,sh}` + `rufino-search-embeddings.{py,sh}`. Indexa todas las notas con Ollama + `nomic-embed-text` (768d) en SQLite + `sqlite-vec`. Storage: `${RUFINO_VAULT_PATH}/_meta/embeddings.sqlite`. Build inicial idempotente (~20 min para ~800 notas, reruns en <1s para deltas). Ver `docs/embeddings-notes.md`.
- **Cross-source person resolver** — `claude/scripts/rufino-person-resolver.{py,sh}`. Detecta posibles duplicados en `_people/` con string similarity (Levenshtein + Jaccard + slug containment) y genera notas en `vault/questions/`. Val responde, se mergea. Ver `docs/person-resolver-notes.md`.
- **MCP server `ask-rufino`** — `claude/mcp/ask-rufino/`. Servidor MCP local (stdio) que expone 6 tools (`search_vault`, `find_person`, `list_decisions`, `list_facts`, `read_note`, `vault_stats`) para que cualquier sesión de Claude Code pueda consultar el vault. Setup: `bash ~/.claude/scripts/setup-mcp-ask-rufino.sh` + agregar block a `~/.claude.json`. Ver `docs/mcp-ask-rufino-notes.md`.

Pendientes (en fases sucesivas del roadmap de expansión, ver `proyectos/rufino/rufino-core/decisionRufinoExpansionPlanFases.md` en el vault de Val):
- Fase 5: Weekly digest + email, bio mensual auto-update, año en revisión.
- Fase 6: Dominios manuales (hardware, salud).

Scripts on-demand (sin cron):
- `rufino-import-plan.sh` — Procesa un doc importado siguiendo un JSON plan.
- `rufino-process-single.sh` — Procesa una sola nota fuera del cron.
- `rufino-reprocess.md` — Prompt one-shot (sin script wrapper) para reprocesar notas existentes y regenerar augmentation. Corré manualmente con env vars exportadas:
  ```bash
  export RUFINO_VAULT_PATH RUFINO_DISPLAY_NAME
  envsubst '${RUFINO_VAULT_PATH} ${RUFINO_DISPLAY_NAME}' < ~/.claude/prompts/rufino-reprocess.md | claude -p --allowedTools "Read,Write,Edit,Glob,Grep,Bash" --dangerously-skip-permissions
  ```
  Es destructivo a nivel frontmatter — leé el prompt antes de correrlo.

## Componentes

- **Hook `obsidianMemoryCheck.sh`** — Al fin de cada conversación, te pide confirmar si hay algo para guardar al vault. Bloquea el stop una vez por sesión.
- **Skill `/remember`** — Mecanismo canónico de escritura al vault. Decide la carpeta destino según el tipo (sesión, decisión, aprendizaje, persona, concepto).
- **Regla `obsidian-memory.md`** — Instruye a Claude a leer `perfil.md` y `preferencias.md` al inicio, detectar proyecto por CWD, crear overview de proyecto nuevo, dispatchar subagent para escrituras al vault.
- **Regla `rufino.md`** — Instruye a Claude sobre cuándo invocar a Rufino y qué taxonomía usar.

## Cómo se llenan las carpetas que arrancan vacías

| Carpeta | Cuándo se llena |
|---|---|
| `conceptos/<x>.md` | Cron `rufino-light-cron` cuando un concepto aparece en ≥2 notas. |
| `proyectos/<x>/overview.md` | Claude lo crea cuando entrás a un CWD nuevo (regla obsidian-memory). |
| `sesiones/<YYYY-MM-DD-tema>.md` | Cuando le pedís a Claude "guardá esto como sesión" (skill `/remember`). |
| `rufino/<proyecto>/<tipo>/` | Cron `rufino-cron` mueve notas crudas procesadas. |
| `rufino/_people/<nombre>.md` | Cron `rufino-cron` cuando detecta una persona nueva. |
| `github/facts/<slug>.md` | Cron `rufino-ingest-github` cuando hay actividad en GitHub el día anterior. |
| `<source>/facts/<slug>.md` | Cualquier ingestor externo configurado (ver `docs/schema-fact-externo.md`). |
| `questions/<slug>.md` | Cualquier procesador que detecte una ambigüedad que solo vos podés resolver (ver `docs/schema-question.md`). |

## Triples tipados

Las relaciones entre notas se guardan en el frontmatter de cada nota:

```yaml
triples:
  - { r: depends-on, o: decisionPricing }
  - { r: led-to, o: aprendizajeRsync }
```

El vocabulario canónico de relaciones está en `_meta/relationship-vocab.md` (incluido en el skeleton). Si querés agregar una relación nueva, edita ese archivo primero.

## Troubleshooting

- **El cron no corre**: chequeá `launchctl list | grep rufino`. Si aparece con `status` distinto de `0` o `-`, mirá el log: `tail -100 $RUFINO_LOG_DIR/rufino-*.log`. Causa común: `RUFINO_VAULT_PATH` no está exportada en el entorno del plist (revisar `<key>EnvironmentVariables</key>`).
- **Las reglas no se aplican**: confirmá que están en `~/.claude/rules/common/` y que Claude las carga (la regla obsidian-memory referencia `perfil.md` — pediéndole a Claude "leé mi perfil" debería buscar el archivo).
- **`/remember` no encuentra el vault**: confirmá que reemplazaste `$VAULT_PATH` en `~/.claude/commands/remember.md` con tu path real.
- **El hook bloquea siempre**: la primera vez por sesión bloquea con código 2 (es el comportamiento deseado). La segunda vez del mismo session_id pasa.
- **`envsubst: command not found`**: instalá `gettext` (`brew install gettext` en macOS).

## Mantenimiento

No hay sync automático entre este repo y `~/.claude/`. Si modificás archivos instalados y querés versionar los cambios, copialos de vuelta al repo y commiteá.

Para upgradear:
```bash
cd ~/rufino-notes-and-memory
git pull
# Repetí los pasos 3-6 de instalación (cp -n no pisa archivos modificados).
launchctl unload ~/Library/LaunchAgents/com.user.rufino-*.plist
launchctl load ~/Library/LaunchAgents/com.user.rufino-*.plist
```

## Desinstalación

```bash
launchctl unload ~/Library/LaunchAgents/com.user.rufino-cron.plist
launchctl unload ~/Library/LaunchAgents/com.user.rufino-light-cron.plist
launchctl unload ~/Library/LaunchAgents/com.user.rufino-lint-cron.plist
rm ~/Library/LaunchAgents/com.user.rufino-*.plist
rm ~/.claude/scripts/rufino-*.sh
rm ~/.claude/prompts/rufino-*.md
rm ~/.claude/rules/common/{obsidian-memory,rufino}.md
rm ~/.claude/hooks/obsidianMemoryCheck.sh
rm ~/.claude/commands/remember.md
```

El vault (`$RUFINO_VAULT_PATH`) **no se toca** en desinstalación — tu data sigue siendo tuya.

## Licencia

MIT.
