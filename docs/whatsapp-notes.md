# WhatsApp ingestor — notas operativas

## Visión general

A diferencia de GitHub / Calendar / Spotify (que tienen APIs oficiales), WhatsApp no expone API pública para clientes personales. La única vía estable es **WhatsApp Web** (el cliente que linkeás como dispositivo secundario desde tu celular).

Rufino usa `whatsapp-web.js`, una librería Node que automatiza Puppeteer contra la UI de WhatsApp Web. La sesión queda persistida en disco (Local Auth), así que el primer login (con QR) es one-time; las próximas corridas reusan la sesión sin pedir QR.

**Daemon vs wake-on-cron**: optamos por **wake-on-cron** — el cron levanta Puppeteer una vez por semana, hace su scrape, baja Puppeteer. Más simple que un daemon 24/7 y suficiente para granularidad semanal. Una corrida típica tarda 30 segundos a 2 minutos.

## Setup (one-time, interactive)

### Paso 1: deps del sistema

```bash
brew install node
```

(npm viene con node.)

### Paso 2: bootstrap

```bash
~/.claude/scripts/setup-whatsapp-auth.sh
```

El script:

1. Verifica que node + npm estén disponibles.
2. Crea `~/.claude/whatsapp-ingestor/` con `package.json` + `whatsapp-init.js` + `whatsapp-scrape.js`.
3. Corre `npm install whatsapp-web.js qrcode-terminal` (la primera vez Puppeteer baja Chromium — 1–2 min de descarga).
4. Crea `~/.claude/whatsapp-session/` con perms `700`.
5. Levanta `whatsapp-init.js` que conecta a WhatsApp Web headless, imprime un QR en terminal.
6. **Vos escaneás el QR** desde tu celular: WhatsApp app → **Settings → Linked Devices → Link a Device** → cámara.
7. Una vez autenticado, la sesión se persiste y el script sale.

Confirmación esperada al final:

```
Listo. Sesión persistida en: /Users/val/.claude/whatsapp-session
Logueado como: <Val display name>
```

### Paso 3: probar el cron manualmente

```bash
RUFINO_VAULT_PATH=/Users/val/Files/vaultlentino \
    ~/.claude/scripts/rufino-ingest-whatsapp.sh
tail -f ~/.claude/logs/rufino/rufino-ingest-whatsapp.log
```

Si todo está OK, vas a ver:

```
=== Rufino ingest-whatsapp run: ...
  Week: YYYY-WW (...)
  Levantando Puppeteer + WhatsApp Web...
  Mensajes recibidos: N | enviados: M | chats activos: K
=== Rufino ingest-whatsapp done: ...
```

Y un raw JSON en `${VAULT_PATH}/whatsapp/raw/<YYYY-WW>.json`, además de facts emitidos por Claude en `${VAULT_PATH}/whatsapp/facts/`.

## Frecuencia y target

- Cron: domingos 05:00 (Weekday=0 en launchd). Después de browsing (03:30), screentime (04:00), spotify (04:30).
- Procesa la **semana ISO anterior**: `date -v-7d +%G-W%V`.
- Override manual: `RUFINO_WHATSAPP_FORCE_WEEK=2026-W19 ~/.claude/scripts/rufino-ingest-whatsapp.sh`.

## Privacy — qué se guarda y qué NO

**SÍ** se guarda (en raw JSON + facts):

- Counts agregados (mensajes recibidos / enviados por contacto).
- Nombres de contactos resueltos por la libreta del celular (es lo que ya tenés en tu agenda).
- IDs hasheados (`id_hash`) — un FNV-1a 32-bit del JID. No-crypto, pero suficiente para dedup local y para evitar exponer el número de teléfono raw.
- Keywords agregados (tokens >= 4 chars, post-stopwords) y su frecuencia agregada — sólo si aparecen en >= 3 chats distintos.

**NO** se guarda:

- Texto literal de mensajes (en ningún lado — ni en raw, ni en facts).
- Frases completas extraídas de mensajes.
- Sentiment per-message o per-conversation.
- Adjuntos, audios, imágenes, ubicaciones.
- Números de teléfono raw (solo el hash).

El cron tiene un **privacy guard** (`jq -e '..|.body?'`): si por bug el scraper emitiera un campo `body` con texto literal en el JSON output, el script aborta antes de avanzar a Claude y elimina el raw.

Si querés ver el contenido raw para debugging, el JSON está en `${VAULT_PATH}/whatsapp/raw/<YYYY-WW>.json`. Considerá agregar `whatsapp/raw/` al `.gitignore` del vault si tu vault está en git.

## Caveats

### Sesión puede expirar

WhatsApp puede invalidar la sesión si:

- Detecta uso anómalo (muchas requests rápidas, behavior tipo bot).
- Val deslinkea el dispositivo desde el celular.
- Pasan ~14 días sin que el celular se conecte a internet (WhatsApp requiere el celular online periódicamente para validar el linked device).

Si la sesión se invalida, el cron va a fallar con un error tipo "auth_failure" o "disconnected" en el log. Fix: re-correr `setup-whatsapp-auth.sh` y escanear el QR de nuevo.

### Puppeteer + Chromium

`whatsapp-web.js` usa Puppeteer, que baja su propio Chromium (no usa el Chrome del sistema). La primera corrida del setup tarda más por esa descarga (~150 MB). Después queda cacheado en `~/.cache/puppeteer/` o similar.

Si tenés problemas con Chromium (ej macOS update rompió compatibilidad), borrá `~/.cache/puppeteer` y re-corré el setup para que se baje fresh.

### whatsapp-web.js es no-oficial

`whatsapp-web.js` no es un cliente oficial de Meta. Funciona mientras WhatsApp Web mantenga su API interna estable. Si WhatsApp Web hace un cambio breaking, la lib eventualmente lo cobertura con un release, pero puede haber lag de días/semanas. Si el cron empieza a fallar consistentemente después de un update de WhatsApp, bajá la última versión:

```bash
cd ~/.claude/whatsapp-ingestor
npm update whatsapp-web.js
```

### Cobertura de la semana

`chat.fetchMessages({limit: 500})` trae los últimos 500 mensajes por chat. Si Val tiene chats muy hablados (grupos grandes) donde >500 mensajes ocurren en una semana, vas a perder los más viejos. Subí el limit si pasa.

Para chats normales, 500 mensajes/semana es muy holgado.

### Tiempo de corrida

Una corrida levanta Puppeteer, conecta a WhatsApp Web, espera que el cliente sincronice, fetchea ~50 chats, y baja Puppeteer. Tiempo total: 30 s a 2 min.

El script tiene un **hard timeout de 5 min** internamente. Si Puppeteer queda colgado (lo que puede pasar si WhatsApp Web cambia algo), el script muere y queda registrado en el log.

## Topic extraction

Es deliberadamente simple: tokenize → strip stopwords español + ruido de mensajería → filtrar tokens >=4 chars → contar ocurrencias agregadas → quedarse con los que aparecen en >= 3 chats distintos.

No usa embeddings, no usa LLM. Pros: rápido, offline, predecible. Contras: pierde nuance semántico (sinónimos no se agrupan, slang argentino puede dominar el top, multi-language chats se mezclan).

Fase 4 puede mejorarlo: embeddings + clustering, o un pass de Claude que mire los keywords y proponga topic labels coherentes. Por ahora, los keywords agregados ya son señal útil para Val sin riesgo de privacy.

## Stopwords actuales

Hardcoded en `whatsapp-scrape.js`. Incluye:

- Articles, pronouns, conjunctions español.
- Verbos auxiliares conjugados (es, son, soy, fue, tengo, tiene...).
- Saludos y muletillas de mensajería (hola, chau, gracias, dale, ok, bueno...).
- Risas y onomatopeya (jaja, jajaja, jjj, ah, eh, mm...).
- Abreviaciones de chat (q, ke, x, pq, xq, tmb...).
- Argentinos (che, boludo, loco, flaco...).
- Pronombres demostrativos, indefinidos.
- Verbos comunes (voy, ir, decir, hay, saber...).
- URLs / extensiones de archivo / palabras de attachment placeholder.

Si Val nota tokens spam que escapan a la lista, agregar a la constante `STOPWORDS` en `~/.claude/whatsapp-ingestor/whatsapp-scrape.js` y commitear el cambio acá también.

## Output esperado por semana

- 1 summary fact: `whatsapp-summary-<YYYY-WW>` (siempre, si hubo activity).
- 0–10 chat-frequency facts: `whatsapp-chat-frequency-<contact-slug>-<YYYY-WW>` (uno por contacto del top-10).
- 0–5 recurring-topic facts: `whatsapp-recurring-topic-<topic-slug>-<YYYY-WW>` (uno por topic con `chats_distinct >= 3`, máx 5).

Topics con 1–2 chats distintos viven sólo en el raw, no se promueven a facts.

## Cross-source person resolution

WhatsApp es la fuente más rica para conectar identidades cross-source (las personas suelen tener nombres reconocibles en WhatsApp aunque en Slack/Calendar usen otros handles). El prompt instruye a Claude a:

1. Cross-checkear nombres del top-10 contra `_people/`.
2. Si hay ambigüedad (un "Diego" en WhatsApp y dos "Diego" en `_people.md`), generar una nota en `questions/` para que Val resuelva.
3. Si hay match exacto, agregar triple `references → <person-slug>` al fact `whatsapp-chat-frequency-...`.

Esto sienta la base para que Fase 4 (cross-source resolver + embeddings) pueda hacer matching más rico.

## Estado del workspace local

```
~/.claude/whatsapp-ingestor/
├── package.json
├── package-lock.json    (generado por npm)
├── node_modules/        (~150 MB con Puppeteer + Chromium)
├── whatsapp-init.js     (one-time auth)
└── whatsapp-scrape.js   (cron worker)

~/.claude/whatsapp-session/    (perms 700)
└── session-rufino/            (data persistida por LocalAuth)
```

Para borrar todo y empezar de cero:

```bash
rm -rf ~/.claude/whatsapp-ingestor
rm -rf ~/.claude/whatsapp-session
~/.claude/scripts/setup-whatsapp-auth.sh
```

## Comandos útiles

Inspeccionar el último raw:

```bash
jq . /Users/val/Files/vaultlentino/whatsapp/raw/$(date -v-7d +%G-W%V).json | less
```

Trigger manual del cron:

```bash
RUFINO_VAULT_PATH=/Users/val/Files/vaultlentino \
    ~/.claude/scripts/rufino-ingest-whatsapp.sh
```

Re-procesar una semana específica:

```bash
RUFINO_WHATSAPP_FORCE_WEEK=2026-W19 \
RUFINO_VAULT_PATH=/Users/val/Files/vaultlentino \
    ~/.claude/scripts/rufino-ingest-whatsapp.sh
```

(Nota: WhatsApp Web sólo muestra mensajes "recientes" — re-procesar una semana muy vieja probablemente devuelva 0 mensajes si el celular ya no tiene esa ventana sincronizada.)

Cargar el LaunchAgent (después de copiar el plist con vault path expandido):

```bash
launchctl load ~/Library/LaunchAgents/com.user.rufino-ingest-whatsapp.plist
```
