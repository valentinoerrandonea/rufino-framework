#!/bin/bash
# ─────────────────────────────────────────────────────────────
#  Rufino — Google Drive OAuth setup (one-time, interactive)
#
#  Flow:
#    1. Lee `credentials.json` desde ~/.claude/secrets/gdrive-credentials.json
#       (descargado desde Google Cloud Console: OAuth 2.0 Client ID tipo
#       "Desktop app").
#    2. Levanta un loopback HTTP server en un puerto random.
#    3. Abre el browser para que Val autorice (scope readonly + metadata).
#    4. Recibe el code, lo cambia por refresh_token.
#    5. Guarda el refresh_token en Keychain:
#         Service: rufino-gdrive-refresh-token
#         Account: val
#
#  Después de esta corrida, `rufino-ingest-gdrive.sh` puede correr sin
#  intervención (usa el refresh_token para sacar access tokens fresh).
#
#  Requires:
#    - python3 (system default OK)
#    - ~/.claude/secrets/gdrive-credentials.json
# ─────────────────────────────────────────────────────────────
set -euo pipefail

CREDENTIALS_FILE="$HOME/.claude/secrets/gdrive-credentials.json"
KEYCHAIN_SERVICE_REFRESH="rufino-gdrive-refresh-token"
KEYCHAIN_SERVICE_CLIENT_ID="rufino-gdrive-client-id"
KEYCHAIN_SERVICE_CLIENT_SECRET="rufino-gdrive-client-secret"
KEYCHAIN_ACCOUNT="val"
SCOPES="https://www.googleapis.com/auth/drive.metadata.readonly https://www.googleapis.com/auth/drive.readonly"

echo "=== Rufino — Google Drive OAuth setup ==="
echo

# Sanity: credentials.json present?
if [ ! -f "$CREDENTIALS_FILE" ]; then
    cat <<EOF
ERROR: No existe $CREDENTIALS_FILE

Pasos previos (manuales, en Google Cloud Console):
  1. Andá a https://console.cloud.google.com → crear o seleccionar proyecto.
  2. APIs & Services → Enable APIs and Services → buscá "Google Drive API"
     y habilitala.
  3. APIs & Services → OAuth consent screen:
       - User Type: External
       - Publishing status: Testing
       - Test users: agregá valentinoerrandonea2002@gmail.com
       - Scopes: agregá .../auth/drive.readonly y .../auth/drive.metadata.readonly
  4. APIs & Services → Credentials → Create Credentials → OAuth client ID:
       - Application type: Desktop app
       - Name: Rufino Drive Ingestor (o lo que quieras)
       - Download JSON
  5. Guardá el JSON descargado como:
       $CREDENTIALS_FILE
  6. Re-corré este script.

Ver docs/gdrive-notes.md para más detalle.
EOF
    exit 1
fi

# Sanity: python3?
if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 no está instalado." >&2
    exit 1
fi

# Validate credentials.json shape
CLIENT_ID=$(python3 -c "import json,sys; d=json.load(open('$CREDENTIALS_FILE')); k=list(d.keys())[0]; print(d[k]['client_id'])" 2>/dev/null || true)
CLIENT_SECRET=$(python3 -c "import json,sys; d=json.load(open('$CREDENTIALS_FILE')); k=list(d.keys())[0]; print(d[k]['client_secret'])" 2>/dev/null || true)

if [ -z "$CLIENT_ID" ] || [ -z "$CLIENT_SECRET" ]; then
    echo "ERROR: $CREDENTIALS_FILE no parece un OAuth client desktop válido." >&2
    echo "       Esperaba un JSON con client_id / client_secret (top-level key 'installed' o 'web')." >&2
    exit 1
fi

echo "Client ID detectado: ${CLIENT_ID:0:30}..."
echo
echo "Levantando loopback server, abriendo browser para autorizar..."
echo

# Run the OAuth dance in Python (stdlib only — no extra deps).
REFRESH_TOKEN=$(CLIENT_ID="$CLIENT_ID" CLIENT_SECRET="$CLIENT_SECRET" SCOPES="$SCOPES" python3 <<'PYEOF'
import os, sys, json, http.server, socket, threading, urllib.parse, urllib.request, webbrowser, secrets

client_id = os.environ["CLIENT_ID"]
client_secret = os.environ["CLIENT_SECRET"]
scopes = os.environ["SCOPES"]

# Pick a random free port on localhost.
with socket.socket() as s:
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]

redirect_uri = f"http://127.0.0.1:{port}/"
state = secrets.token_urlsafe(16)

auth_url = (
    "https://accounts.google.com/o/oauth2/v2/auth?"
    + urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scopes,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    })
)

received = {}

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a, **kw): pass
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        if "code" in params and params.get("state", [""])[0] == state:
            received["code"] = params["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<html><body><h2>Rufino: autorizacion OK. Podes cerrar esta ventana.</h2></body></html>")
        else:
            self.send_response(400)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Fallo: code/state invalido.")

server = http.server.HTTPServer(("127.0.0.1", port), Handler)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()

print(f"  Abriendo: {auth_url}", file=sys.stderr)
try:
    webbrowser.open(auth_url)
except Exception:
    pass
print(f"  Si el browser no se abrio, pega esta URL en cualquier navegador:\n  {auth_url}", file=sys.stderr)
print("  Esperando autorizacion...", file=sys.stderr)

# Wait up to 5 minutes.
import time
deadline = time.time() + 300
while "code" not in received and time.time() < deadline:
    time.sleep(0.5)
server.shutdown()

if "code" not in received:
    print("ERROR: timeout esperando autorizacion (5 min).", file=sys.stderr)
    sys.exit(1)

# Exchange code for tokens.
data = urllib.parse.urlencode({
    "code": received["code"],
    "client_id": client_id,
    "client_secret": client_secret,
    "redirect_uri": redirect_uri,
    "grant_type": "authorization_code",
}).encode()

req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data)
try:
    with urllib.request.urlopen(req) as resp:
        tok = json.loads(resp.read())
except urllib.error.HTTPError as e:
    print(f"ERROR cambiando code por token: {e.read().decode()}", file=sys.stderr)
    sys.exit(1)

rt = tok.get("refresh_token")
if not rt:
    print("ERROR: la respuesta no incluye refresh_token. Probable: el usuario ya autorizo antes — revocá en https://myaccount.google.com/permissions y reintentá.", file=sys.stderr)
    sys.exit(1)

# Stdout = the token (clean). Stderr = log.
print(rt)
PYEOF
)

if [ -z "$REFRESH_TOKEN" ]; then
    echo "ERROR: no se obtuvo refresh_token." >&2
    exit 1
fi

# Guardar las 3 keys en Keychain. Si ya existe, sobreescribir (-U).
# rufino-ingest-gdrive.sh y rufino-ingest-youtube.sh necesitan las 3.
security add-generic-password -s "$KEYCHAIN_SERVICE_REFRESH"       -a "$KEYCHAIN_ACCOUNT" -w "$REFRESH_TOKEN"  -U >/dev/null
security add-generic-password -s "$KEYCHAIN_SERVICE_CLIENT_ID"     -a "$KEYCHAIN_ACCOUNT" -w "$CLIENT_ID"      -U >/dev/null
security add-generic-password -s "$KEYCHAIN_SERVICE_CLIENT_SECRET" -a "$KEYCHAIN_ACCOUNT" -w "$CLIENT_SECRET"  -U >/dev/null

echo
echo "OK. Credenciales guardadas en Keychain (account=$KEYCHAIN_ACCOUNT):"
echo "  $KEYCHAIN_SERVICE_REFRESH"
echo "  $KEYCHAIN_SERVICE_CLIENT_ID"
echo "  $KEYCHAIN_SERVICE_CLIENT_SECRET"
echo
echo "Para verificar:"
echo "  security find-generic-password -s $KEYCHAIN_SERVICE_REFRESH -a $KEYCHAIN_ACCOUNT -w"
echo
echo "Ya podes correr rufino-ingest-gdrive.sh / rufino-ingest-youtube.sh o esperar al cron."
