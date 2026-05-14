# Weekly digest — operación

Fase 5 — output automático que sintetiza la semana de Val y le manda un email viernes 18:00.

## Qué hace

Cron viernes 18:00 (LaunchAgent `com.user.rufino-digest-weekly`):

1. Lee facts de los últimos 7 días de **todos** los ingestors disponibles (`github`, `calendar`, `screentime`, `browsing`, `spotify`, `gdrive`, `youtube`, `whatsapp`).
2. Lee notas `decision*`, `aprendizaje*`, `sesion*` modificadas en la ventana.
3. Lee pendientes activos próximos (`rufino/_pendientes.md`).
4. Lee questions con `status: pending`.
5. Genera un digest narrativo en `${RUFINO_VAULT_PATH}/general/digests/<YYYY-Wxx>.md`.
6. Manda email HTML a `valentinoerrandonea2002@gmail.com`.
7. Marca `email_sent: true` en el frontmatter del digest si el send fue exitoso.

## Ventana de tiempo

- **Default**: el viernes 18:00 corre con la **semana ISO anterior** (lunes → domingo de la semana pasada, ya cerrada). La semana corriente está mid-week (sábado y domingo todavía no pasaron), por eso no la cubrimos por default.
- **Override**: setear `RUFINO_DIGEST_FORCE_WEEK=YYYY-Wxx` para regenerar una semana específica (formato ISO con `W`, ej `2026-W19`).

## Setup (one-time)

### 1. Generar App Password en Gmail

Como el cron necesita mandar email a sí mismo y Google bloquea SMTP con la contraseña normal de la cuenta, hay que generar un **app password** específico:

1. Asegurate de tener **2FA activado** en `valentinoerrandonea2002@gmail.com` (requisito de Google para app passwords).
2. Andá a https://myaccount.google.com/apppasswords.
3. Generá un nuevo app password. Nombrelo "Rufino digest" o similar.
4. Copiá los 16 caracteres (sin espacios) que te muestra Google.

### 2. Guardar el app password en Keychain

```bash
security add-generic-password \
  -s rufino-gmail-app-password \
  -a val \
  -w '<16-char-app-password>' \
  -U
```

El flag `-U` hace update si ya existe. El helper `rufino-send-email.py` lee de ahí (service: `rufino-gmail-app-password`, account: `val`).

### 3. Test del helper de email

```bash
python3 ~/.claude/scripts/rufino-send-email.py \
  --to valentinoerrandonea2002@gmail.com \
  --subject "Rufino — Setup test" \
  --body-plain "Si recibiste esto, el setup de Gmail SMTP funciona."
```

Si exit 0 y el email llega: listo. Si exit 1: el mensaje al stderr te dice qué falló (Keychain vacío, auth contra Gmail, etc.).

### 4. Instalar el LaunchAgent

```bash
# Renderizá el plist con tu $HOME real
sed "s|__HOME__|$HOME|g" \
  ~/Files/rufino/system/launchd/com.user.rufino-digest-weekly.plist \
  > ~/Library/LaunchAgents/com.user.rufino-digest-weekly.plist

# Editá las EnvironmentVariables vacías (RUFINO_VAULT_PATH y RUFINO_DISPLAY_NAME)
# o asegurate de que estén en tu zshenv y el LaunchAgent las herede.
# En la práctica, conviene meter los valores hardcoded en el plist:
#   <key>RUFINO_VAULT_PATH</key>
#   <string>/Users/val/Files/vaultlentino</string>
#   <key>RUFINO_DISPLAY_NAME</key>
#   <string>Val</string>

launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.user.rufino-digest-weekly.plist
```

Verificá:
```bash
launchctl print gui/$(id -u)/com.user.rufino-digest-weekly | head
```

## Cómo correr manualmente

### Dry run (sin email, solo genera el archivo)

```bash
RUFINO_VAULT_PATH=/Users/val/Files/vaultlentino \
RUFINO_DIGEST_DRY_RUN=1 \
bash ~/.claude/scripts/rufino-digest-weekly.sh
```

### Correr con email real

```bash
RUFINO_VAULT_PATH=/Users/val/Files/vaultlentino \
bash ~/.claude/scripts/rufino-digest-weekly.sh
```

### Regenerar una semana específica

```bash
RUFINO_VAULT_PATH=/Users/val/Files/vaultlentino \
RUFINO_DIGEST_FORCE_WEEK=2026-W19 \
RUFINO_DIGEST_DRY_RUN=1 \
bash ~/.claude/scripts/rufino-digest-weekly.sh
```

## Outputs

- **Vault**: `${RUFINO_VAULT_PATH}/general/digests/YYYY-Wxx.md` con frontmatter completo (id, tags, iso_week, window_start/end, generated, email_sent, triples).
- **Email**: subject `Rufino — Digest semanal YYYY-Wxx`, body HTML renderizado desde el markdown.
- **Log**: `~/.claude/logs/rufino/rufino-digest-weekly.log`.

## Troubleshooting

| Síntoma | Causa probable | Fix |
|---|---|---|
| Email no llega | App password inválido | Regenerá en `myaccount.google.com/apppasswords` y resaveá al Keychain. |
| Email no llega | App password no está en Keychain | Corré `security find-generic-password -s rufino-gmail-app-password -a val -w`. Si error, resaveá. |
| Email no llega | 2FA desactivado en Gmail | Activalo. App passwords requiere 2FA. |
| Email en spam | Gmail clasifica el self-send como filter | Marcalo como no-spam la primera vez; Gmail aprende. |
| `RUFINO_VAULT_PATH must be set` | Env var no exportada en el LaunchAgent | Editá el plist y poné el path absoluto en `EnvironmentVariables`. |
| Digest vacío / "Semana sin actividad" | Ningún ingestor corrió esa semana | Verificá `~/.claude/logs/rufino/rufino-ingest-*.log` de la semana — si están vacíos, los crons no corrieron. |
| Lock file viejo bloquea corrida | Crash previo dejó `.digest-weekly.lock` | El script tiene stale-lock check con `kill -0`. Si igual no anda: `rm ${RUFINO_VAULT_PATH}/_meta/.digest-weekly.lock`. |
| Helper `rufino-send-email.py: command not found` | Falta copiar a `~/.claude/scripts/` | `cp ~/Files/rufino/claude/scripts/rufino-send-email.py ~/.claude/scripts/ && chmod +x ~/.claude/scripts/rufino-send-email.py`. |

## Notas técnicas

- **Markdown → HTML**: el helper `rufino-send-email.py` usa un parser regex propio (stdlib `re` + `email.mime`). No requiere `pip install`. Soporta headers, listas (ul/ol), bold/italic, código inline + fenced, wikilinks (como `<code>`), párrafos, links markdown estándar. Frontmatter YAML se descarta del body HTML.
- **Transport**: `smtp.gmail.com:587` con STARTTLS. Login con `valentinoerrandonea2002@gmail.com` + app password.
- **From/To**: ambos `valentinoerrandonea2002@gmail.com` (val a sí mismo).
- **Subject convention**: `Rufino — Digest semanal YYYY-Wxx`.
- **Modelo Claude**: `sonnet`. Si los digests salen mediocres, subir a `opus` editando el script.
- **`allowedTools`**: `Read,Write,Edit,Glob,Grep,Bash`. Sin permitir red ni tools nuevas (el email lo manda el helper Python a través de Bash, lo cual ya está permitido).
