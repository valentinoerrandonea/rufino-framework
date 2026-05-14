#!/bin/bash
# ─────────────────────────────────────────────────────────────
#  Rufino — WhatsApp Web auth bootstrap (one-time, interactive)
#
#  Corré este script UNA VEZ para autenticar a Rufino contra
#  WhatsApp Web. Levanta Puppeteer headless con `whatsapp-web.js`,
#  imprime el QR en terminal, esperá que Val lo escanee desde la
#  app de WhatsApp en su celular (Settings → Linked Devices →
#  Link a Device). Una vez autenticado, la sesión queda persistida
#  en `~/.claude/whatsapp-session/` y el cron semanal
#  (`rufino-ingest-whatsapp.sh`) la reusa sin pedir QR.
#
#  Pre-requisitos:
#    - Node.js (`brew install node`)
#    - npm
#    - Conectividad para que npm baje deps + Puppeteer descargue
#      Chromium la primera vez (puede tardar 1–2 min).
#
#  Side effects:
#    - Crea `~/.claude/whatsapp-ingestor/` con package.json + scripts.
#    - Instala `whatsapp-web.js` y `qrcode-terminal` ahí.
#    - Crea `~/.claude/whatsapp-session/` con perms 700.
# ─────────────────────────────────────────────────────────────
set -euo pipefail

INGESTOR_DIR="$HOME/.claude/whatsapp-ingestor"
SESSION_DIR="$HOME/.claude/whatsapp-session"

# ─── Sanity: deps ───
if ! command -v node >/dev/null 2>&1; then
    cat >&2 <<EOF
ERROR: node no está instalado.

Instalá Node.js:
  brew install node

Después corré de nuevo este script.
EOF
    exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
    echo "ERROR: npm no está instalado (vino con node, raro que falte)." >&2
    exit 1
fi

NODE_VERSION=$(node --version)
echo "─────────────────────────────────────────────────────────────"
echo "Rufino — WhatsApp Web auth bootstrap"
echo "─────────────────────────────────────────────────────────────"
echo "Node: $NODE_VERSION"
echo "Ingestor dir:  $INGESTOR_DIR"
echo "Session dir:   $SESSION_DIR"
echo

# ─── Crear directorios ───
mkdir -p "$INGESTOR_DIR"
mkdir -p "$SESSION_DIR"
chmod 700 "$SESSION_DIR"

# ─── package.json ───
if [ ! -f "$INGESTOR_DIR/package.json" ]; then
    cat > "$INGESTOR_DIR/package.json" <<'EOF'
{
  "name": "rufino-whatsapp-ingestor",
  "version": "1.0.0",
  "private": true,
  "description": "Rufino WhatsApp Web ingestor (whatsapp-web.js + puppeteer)",
  "type": "commonjs",
  "scripts": {
    "auth": "node whatsapp-init.js",
    "scrape": "node whatsapp-scrape.js"
  },
  "dependencies": {
    "qrcode-terminal": "^0.12.0",
    "whatsapp-web.js": "^1.23.0"
  }
}
EOF
    echo "  package.json creado."
fi

# ─── whatsapp-init.js (auth flow) ───
cat > "$INGESTOR_DIR/whatsapp-init.js" <<'EOF'
// Rufino — WhatsApp auth bootstrap.
// Levanta whatsapp-web.js con LocalAuth, imprime QR en terminal,
// espera a que Val lo escanee, persiste la sesión y exit.

const { Client, LocalAuth } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');
const path = require('path');

const SESSION_DIR = process.env.RUFINO_WHATSAPP_SESSION_DIR
    || path.join(process.env.HOME, '.claude', 'whatsapp-session');

console.log('Iniciando cliente WhatsApp Web...');
console.log('Sesión: ' + SESSION_DIR);
console.log('Puppeteer va a bajar Chromium si es la primera vez (puede tardar).');
console.log('');

const client = new Client({
    authStrategy: new LocalAuth({
        clientId: 'rufino',
        dataPath: SESSION_DIR,
    }),
    puppeteer: {
        headless: true,
        args: [
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-dev-shm-usage',
        ],
    },
});

client.on('qr', (qr) => {
    console.log('─────────────────────────────────────────────────────────────');
    console.log('Escaneá este QR con WhatsApp en tu celular:');
    console.log('  WhatsApp → Settings → Linked Devices → Link a Device');
    console.log('─────────────────────────────────────────────────────────────');
    qrcode.generate(qr, { small: true });
});

client.on('authenticated', () => {
    console.log('');
    console.log('Autenticado. Persistiendo sesión...');
});

client.on('auth_failure', (msg) => {
    console.error('ERROR: auth_failure → ' + msg);
    process.exit(1);
});

client.on('ready', async () => {
    try {
        const info = client.info;
        const me = (info && info.pushname) || (info && info.wid && info.wid.user) || '(unknown)';
        console.log('');
        console.log('─────────────────────────────────────────────────────────────');
        console.log('Listo. Sesión persistida en: ' + SESSION_DIR);
        console.log('Logueado como: ' + me);
        console.log('');
        console.log('A partir de ahora el cron rufino-ingest-whatsapp puede correr solo.');
        console.log('Para probarlo manualmente:');
        console.log('');
        console.log('  RUFINO_VAULT_PATH=/Users/val/Files/vaultlentino \\');
        console.log('    ~/.claude/scripts/rufino-ingest-whatsapp.sh');
        console.log('─────────────────────────────────────────────────────────────');
    } catch (err) {
        console.error('Warning fetching info: ' + err.message);
    }
    await client.destroy();
    process.exit(0);
});

client.on('disconnected', (reason) => {
    console.error('disconnected: ' + reason);
    process.exit(1);
});

// Hard timeout: 5 minutos para que Val escanee.
setTimeout(() => {
    console.error('ERROR: timeout esperando QR scan (5 min).');
    process.exit(1);
}, 5 * 60 * 1000);

client.initialize().catch((err) => {
    console.error('ERROR al inicializar cliente: ' + err.message);
    process.exit(1);
});
EOF

# ─── whatsapp-scrape.js (cron worker) ───
cat > "$INGESTOR_DIR/whatsapp-scrape.js" <<'EOF'
// Rufino — WhatsApp scrape semanal.
// Usado por el cron rufino-ingest-whatsapp.sh. Levanta whatsapp-web.js
// con sesión persistida, fetchea chats + mensajes de la última semana,
// agrega counts + keywords (sin texto literal) y dumpea JSON a stdout.
//
// Env:
//   RUFINO_WHATSAPP_SESSION_DIR — path a la sesión (default ~/.claude/whatsapp-session)
//   RUFINO_WHATSAPP_WEEK_START  — YYYY-MM-DD (lunes ISO)
//   RUFINO_WHATSAPP_WEEK_END    — YYYY-MM-DD (domingo ISO)
//   RUFINO_WHATSAPP_WEEK        — YYYY-WW (ej 2026-W19)
//
// Output: JSON con shape definido en raw schema. NO incluye texto literal
// de mensajes en ningún campo del output.

const { Client, LocalAuth } = require('whatsapp-web.js');
const path = require('path');

const SESSION_DIR = process.env.RUFINO_WHATSAPP_SESSION_DIR
    || path.join(process.env.HOME, '.claude', 'whatsapp-session');

// Período: por default semanal. Override via RUFINO_WHATSAPP_PERIOD_* para
// custom range (ej backfill anual).
const PERIOD_LABEL = process.env.RUFINO_WHATSAPP_PERIOD_LABEL
    || process.env.RUFINO_WHATSAPP_WEEK || '';
const PERIOD_START = process.env.RUFINO_WHATSAPP_PERIOD_START
    || process.env.RUFINO_WHATSAPP_WEEK_START || '';
const PERIOD_END = process.env.RUFINO_WHATSAPP_PERIOD_END
    || process.env.RUFINO_WHATSAPP_WEEK_END || '';

if (!PERIOD_LABEL || !PERIOD_START || !PERIOD_END) {
    console.error('ERROR: falta RUFINO_WHATSAPP_PERIOD_LABEL / PERIOD_START / PERIOD_END (o legacy WEEK*)');
    process.exit(1);
}

let EXCLUDED_GROUPS = [];
try {
    EXCLUDED_GROUPS = JSON.parse(process.env.RUFINO_WHATSAPP_EXCLUDED_GROUPS || '[]');
} catch (e) {
    console.error('WARN: RUFINO_WHATSAPP_EXCLUDED_GROUPS inválido — usando []');
}
const MIN_MESSAGES = parseInt(process.env.RUFINO_WHATSAPP_MIN_MESSAGES || '0', 10);
const FETCH_LIMIT = parseInt(process.env.RUFINO_WHATSAPP_FETCH_LIMIT || '500', 10);
const TOP_N = parseInt(process.env.RUFINO_WHATSAPP_TOP_N || '10', 10);

const startTs = Math.floor(new Date(`${PERIOD_START}T00:00:00`).getTime() / 1000);
const endTs = Math.floor(new Date(`${PERIOD_END}T23:59:59`).getTime() / 1000);

// Stopwords español + ruido de mensajería. Hardcoded — Fase 4 puede mejorar.
const STOPWORDS = new Set([
    'el','la','los','las','de','en','un','una','que','y','a','por','para',
    'con','no','se','lo','le','su','sus','esto','eso','este','esta','estos','estas',
    'al','del','es','son','soy','era','fue','ser','estar','está','están',
    'mi','tu','te','me','nos','os','les','yo','vos','tú','él','ella','ellos','ellas','nosotros',
    'pero','si','sí','muy','más','menos','tan','tanto','también','tambien','tampoco',
    'ya','aún','aun','hoy','ayer','mañana','manana','después','despues','antes','ahora',
    'hola','holaa','buenas','chau','adiós','adios','gracias','dale','ok','okey','bueno',
    'jaja','jajaja','jajajaja','jjj','jjjj','ja','j','q','ke','x','pq','xq','tmb',
    'che','boludo','bolu','wn','loco','flaco','amigo','amiga','hermano','hermana',
    'cómo','como','cuando','donde','dónde','qué','que','quién','quien','cuál','cual',
    'hay','ha','han','he','haber','tengo','tener','tenés','tenes','tiene','tienen',
    'voy','vas','va','vamos','van','ir','vine','viene','vienen',
    'sé','se','sabe','saben','dice','dijo','digo','dije','decir',
    'eso','esa','esos','esas','ese','algo','alguien','alguna','algún','algun',
    'todo','toda','todos','todas','nada','nadie','ninguno','ninguna',
    'mucho','mucha','muchos','muchas','poco','poca','pocos','pocas',
    'ah','eh','oh','uh','mm','mmm','aja','ajá','aha','ahá','aha','hmm',
    'http','https','www','com','net','org','jpg','jpeg','png','gif','mp4',
    'audio','video','image','imagen','documento','sticker','gif','message',
    'pm','am','sí','no','tal','vez','solo','sola','solos','solas',
]);

// Sanitiza: removes URLs, mentions, emoji-only tokens. Returns array of words.
function tokenize(text) {
    if (!text || typeof text !== 'string') return [];
    // Strip URLs, mentions, code-like blobs.
    const cleaned = text
        .toLowerCase()
        .replace(/https?:\/\/\S+/g, ' ')
        .replace(/@\d+/g, ' ')
        .replace(/[^a-záéíóúñü0-9\s]/gi, ' ')
        .replace(/\s+/g, ' ')
        .trim();
    if (!cleaned) return [];
    return cleaned.split(' ').filter((w) => {
        if (w.length < 4) return false;
        if (STOPWORDS.has(w)) return false;
        if (/^\d+$/.test(w)) return false;
        return true;
    });
}

function slugify(s) {
    if (!s) return '';
    return s
        .toLowerCase()
        .normalize('NFD').replace(/[̀-ͯ]/g, '') // strip accents
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-+|-+$/g, '')
        .slice(0, 60);
}

async function main() {
    const client = new Client({
        authStrategy: new LocalAuth({
            clientId: 'rufino',
            dataPath: SESSION_DIR,
        }),
        puppeteer: {
            headless: true,
            args: [
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
            ],
        },
    });

    let resolveReady, rejectReady;
    const readyPromise = new Promise((res, rej) => { resolveReady = res; rejectReady = rej; });

    client.on('ready', () => resolveReady());
    client.on('auth_failure', (msg) => rejectReady(new Error('auth_failure: ' + msg)));
    client.on('disconnected', (reason) => rejectReady(new Error('disconnected: ' + reason)));

    // Hard timeout for whole run: 5 minutes.
    const hardTimeout = setTimeout(() => {
        console.error('ERROR: hard timeout (5 min)');
        process.exit(1);
    }, 5 * 60 * 1000);

    client.initialize().catch((err) => rejectReady(err));

    await readyPromise;

    // Pull chats.
    const chats = await client.getChats();

    let totalReceived = 0;
    let totalSent = 0;
    let chatsActive = 0;
    const perContact = []; // {name, id, slug, isGroup, received, sent, total, tokens: Map}
    const globalTokens = new Map(); // token -> {count, chatIds:Set}

    for (const chat of chats) {
        try {
            const chatName = chat.name || '';
            const chatNameLower = chatName.toLowerCase();
            const isExcluded = EXCLUDED_GROUPS.some(g => g.toLowerCase() === chatNameLower);
            if (isExcluded) {
                console.error('SKIP excluded group: ' + chatName);
                continue;
            }
            const msgs = await chat.fetchMessages({ limit: FETCH_LIMIT });
            const inWindow = msgs.filter((m) => m.timestamp >= startTs && m.timestamp <= endTs);
            if (inWindow.length === 0) continue;
            if (inWindow.length < MIN_MESSAGES) {
                console.error('SKIP under-threshold (' + inWindow.length + ' < ' + MIN_MESSAGES + '): ' + chatName);
                continue;
            }

            chatsActive += 1;

            let received = 0;
            let sent = 0;
            const contactTokens = new Map();

            for (const m of inWindow) {
                if (m.fromMe) sent += 1; else received += 1;
                if (typeof m.body === 'string' && m.body.length > 0 && m.type === 'chat') {
                    const tokens = tokenize(m.body);
                    for (const t of tokens) {
                        contactTokens.set(t, (contactTokens.get(t) || 0) + 1);
                    }
                }
            }

            totalReceived += received;
            totalSent += sent;

            // Resolve contact name (best-effort).
            let displayName = chat.name || '';
            if (!displayName && chat.contact) {
                displayName = chat.contact.pushname || chat.contact.name || chat.contact.number || '';
            }
            if (!displayName) displayName = chat.id && chat.id.user ? chat.id.user : '(unknown)';

            const contactId = chat.id && chat.id._serialized ? chat.id._serialized : String(chat.id);

            // Aggregate tokens up to global pool, weighted by chat presence.
            for (const [tok, cnt] of contactTokens.entries()) {
                if (!globalTokens.has(tok)) globalTokens.set(tok, { count: 0, chats: new Set() });
                const entry = globalTokens.get(tok);
                entry.count += cnt;
                entry.chats.add(contactId);
            }

            const sortedContactTokens = Array.from(contactTokens.entries())
                .sort((a, b) => b[1] - a[1])
                .slice(0, 30)
                .map(([token, count]) => ({ token, count }));

            perContact.push({
                name: displayName,
                slug: slugify(displayName),
                id_hash: shortHash(contactId),
                is_group: !!chat.isGroup,
                received,
                sent,
                total: received + sent,
                top_tokens: sortedContactTokens,
            });
        } catch (err) {
            // Skip bad chat, log to stderr (no a stdout — stdout es el JSON).
            console.error('WARN: chat ' + (chat && chat.name) + ' skipped: ' + err.message);
        }
    }

    perContact.sort((a, b) => b.total - a.total);

    // Topics: tokens que aparecen en >= 3 chats distintos. Top 20.
    const recurringTopics = [];
    for (const [tok, entry] of globalTokens.entries()) {
        if (entry.chats.size >= 3) {
            recurringTopics.push({
                token: tok,
                slug: slugify(tok),
                occurrences: entry.count,
                chats_distinct: entry.chats.size,
            });
        }
    }
    recurringTopics.sort((a, b) => {
        if (b.chats_distinct !== a.chats_distinct) return b.chats_distinct - a.chats_distinct;
        return b.occurrences - a.occurrences;
    });
    const topTopics = recurringTopics.slice(0, 20);

    const output = {
        period: PERIOD_LABEL,
        period_start: PERIOD_START,
        period_end: PERIOD_END,
        week: PERIOD_LABEL,
        week_start: PERIOD_START,
        week_end: PERIOD_END,
        config: { excluded_groups: EXCLUDED_GROUPS, min_messages: MIN_MESSAGES, fetch_limit: FETCH_LIMIT, top_n: TOP_N },
        total_received: totalReceived,
        total_sent: totalSent,
        chats_active: chatsActive,
        top_contacts: perContact.slice(0, TOP_N),
        recurring_topics: topTopics,
        // CRITICAL: nunca incluir texto literal de mensajes.
    };

    process.stdout.write(JSON.stringify(output, null, 2));

    clearTimeout(hardTimeout);
    await client.destroy();
    process.exit(0);
}

function shortHash(s) {
    // FNV-1a 32-bit, hex, 8 chars. No-crypto pero suficiente para dedup local
    // y para evitar exponer el número de teléfono raw en el JSON.
    let h = 0x811c9dc5;
    for (let i = 0; i < s.length; i++) {
        h ^= s.charCodeAt(i);
        h = (h + ((h << 1) + (h << 4) + (h << 7) + (h << 8) + (h << 24))) >>> 0;
    }
    return h.toString(16).padStart(8, '0');
}

main().catch((err) => {
    console.error('FATAL: ' + (err && err.stack ? err.stack : err));
    process.exit(1);
});
EOF

echo "  whatsapp-init.js + whatsapp-scrape.js escritos."
echo

# ─── npm install ───
echo "Instalando deps (whatsapp-web.js + qrcode-terminal)..."
echo "  (la primera vez Puppeteer baja Chromium, puede tardar 1–2 min)"
echo
(
    cd "$INGESTOR_DIR"
    npm install --no-audit --no-fund --silent
)

# ─── Correr auth ───
echo
echo "─────────────────────────────────────────────────────────────"
echo "Iniciando flow de autenticación. Va a aparecer un QR — escaneálo"
echo "con WhatsApp en tu celular (Settings → Linked Devices → Link a Device)."
echo "─────────────────────────────────────────────────────────────"
echo

cd "$INGESTOR_DIR"
RUFINO_WHATSAPP_SESSION_DIR="$SESSION_DIR" node whatsapp-init.js
