#!/bin/bash
# ─────────────────────────────────────────────────────────────
#  Rufino — Spotify OAuth bootstrap (one-time, interactive)
#
#  Corré este script UNA VEZ para autorizar a Rufino contra tu cuenta
#  de Spotify y guardar un refresh_token persistente en macOS Keychain.
#  El cron (`rufino-ingest-spotify.sh`) lo consume después para
#  generar access_tokens frescos.
#
#  Pre-requisitos:
#    1. Credenciales en Keychain:
#         security find-generic-password -s rufino-spotify-client-id -a val -w
#         security find-generic-password -s rufino-spotify-client-secret -a val -w
#    2. En el dashboard de Spotify (developer.spotify.com/dashboard),
#       editar la app y **agregar como Redirect URI**:
#         http://127.0.0.1:8765/callback
#       (sin trailing slash, exactly así).
#
#  Flow:
#    1. Levantamos un mini HTTP server en 127.0.0.1:8765 con `nc` que
#       responde 1 request y captura `code` del query string.
#    2. Imprimimos la URL de authorize y la abrimos en el browser.
#    3. Cuando Val autoriza, Spotify redirige a 127.0.0.1:8765/callback
#       con `?code=XXX`. `nc` captura, parseamos el code.
#    4. POST a /api/token con grant_type=authorization_code → access +
#       refresh tokens.
#    5. Guardamos el refresh_token en Keychain.
# ─────────────────────────────────────────────────────────────
set -euo pipefail

REDIRECT_URI="http://127.0.0.1:8765/callback"
SCOPE="user-read-recently-played"
PORT=8765

# ─── Sanity ───
for bin in curl jq nc python3 security; do
    if ! command -v "$bin" >/dev/null 2>&1; then
        echo "ERROR: $bin no está instalado." >&2
        exit 1
    fi
done

if lsof -iTCP:$PORT -sTCP:LISTEN >/dev/null 2>&1; then
    echo "ERROR: el puerto $PORT ya está en uso. Liberalo y reintentá." >&2
    exit 1
fi

# ─── Credenciales ───
CLIENT_ID=$(security find-generic-password -s rufino-spotify-client-id -a val -w 2>/dev/null || true)
CLIENT_SECRET=$(security find-generic-password -s rufino-spotify-client-secret -a val -w 2>/dev/null || true)

if [ -z "$CLIENT_ID" ] || [ -z "$CLIENT_SECRET" ]; then
    cat >&2 <<EOF
ERROR: No encontré las credenciales en Keychain.

Guardá primero:
  security add-generic-password -s rufino-spotify-client-id     -a val -w "<CLIENT_ID>"
  security add-generic-password -s rufino-spotify-client-secret -a val -w "<CLIENT_SECRET>"

Después corré de nuevo este script.
EOF
    exit 1
fi

# ─── Construir authorize URL ───
STATE=$(python3 -c "import secrets; print(secrets.token_urlsafe(16))")

# URL-encode helper (python3 quote_plus)
urlencode() {
    python3 -c "import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=''))" "$1"
}

AUTH_URL="https://accounts.spotify.com/authorize"
AUTH_URL+="?response_type=code"
AUTH_URL+="&client_id=$(urlencode "$CLIENT_ID")"
AUTH_URL+="&scope=$(urlencode "$SCOPE")"
AUTH_URL+="&redirect_uri=$(urlencode "$REDIRECT_URI")"
AUTH_URL+="&state=$(urlencode "$STATE")"

cat <<EOF
─────────────────────────────────────────────────────────────
Rufino — Spotify OAuth bootstrap
─────────────────────────────────────────────────────────────
Pre-requisito: la app de Spotify (developer.spotify.com/dashboard)
debe tener registrada como Redirect URI:

    $REDIRECT_URI

Si no la registraste, hacelo antes de continuar (Edit → Redirect URIs).

Voy a abrir esta URL en tu browser; autorizá la app:

$AUTH_URL

Si no se abre sola, copiala y pegala en el browser.
─────────────────────────────────────────────────────────────
EOF

# Intentar abrir el browser (no fatal si falla)
if command -v open >/dev/null 2>&1; then
    open "$AUTH_URL" 2>/dev/null || true
fi

# ─── Mini HTTP server para capturar callback ───
echo "Esperando callback en $REDIRECT_URI ..."

CALLBACK_RAW=$(mktemp -t rufino-spotify-cb-XXXXXX)
trap 'rm -f "$CALLBACK_RAW"' EXIT

# nc -l escucha 1 conexión. Capturamos la request line y respondemos OK.
# El primer chunk de stdin trae "GET /callback?code=...&state=... HTTP/1.1".
# Respondemos con HTTP/1.1 200 y cerramos.
{
    printf 'HTTP/1.1 200 OK\r\n'
    printf 'Content-Type: text/html; charset=utf-8\r\n'
    printf 'Connection: close\r\n'
    printf '\r\n'
    printf '<html><body style="font-family: system-ui; padding: 2em;"><h1>Rufino — Spotify autorizado.</h1><p>Podés cerrar esta pestaña y volver a la terminal.</p></body></html>'
} | nc -l "$PORT" > "$CALLBACK_RAW" 2>/dev/null || {
    echo "ERROR: el listener de nc falló." >&2
    exit 1
}

# Parsear la request line: "GET /callback?code=XXX&state=YYY HTTP/1.1"
REQ_LINE=$(head -n 1 "$CALLBACK_RAW" | tr -d '\r')
QUERY=$(echo "$REQ_LINE" | awk '{print $2}' | sed -n 's|^/callback?||p')

if [ -z "$QUERY" ]; then
    echo "ERROR: callback recibido pero sin query string. Request: $REQ_LINE" >&2
    exit 1
fi

# Extraer code y state (parseo simple, no maneja URL-encoding complejo
# pero `code` y `state` de Spotify no traen chars especiales que necesiten decode)
CODE=$(echo "$QUERY" | tr '&' '\n' | grep '^code=' | head -n 1 | cut -d= -f2-)
GOT_STATE=$(echo "$QUERY" | tr '&' '\n' | grep '^state=' | head -n 1 | cut -d= -f2-)
ERR=$(echo "$QUERY" | tr '&' '\n' | grep '^error=' | head -n 1 | cut -d= -f2-)

if [ -n "$ERR" ]; then
    echo "ERROR: Spotify devolvió error: $ERR" >&2
    exit 1
fi

if [ -z "$CODE" ]; then
    echo "ERROR: no extraje 'code' del callback. Query: $QUERY" >&2
    exit 1
fi

if [ "$GOT_STATE" != "$STATE" ]; then
    echo "ERROR: state mismatch (CSRF guard). Esperaba '$STATE', vino '$GOT_STATE'." >&2
    exit 1
fi

echo "Callback OK — tengo el authorization code. Intercambiando por tokens..."

# ─── Intercambiar code por tokens ───
TOKEN_RESPONSE=$(curl -s -X POST "https://accounts.spotify.com/api/token" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -u "${CLIENT_ID}:${CLIENT_SECRET}" \
    --data-urlencode "grant_type=authorization_code" \
    --data-urlencode "code=$CODE" \
    --data-urlencode "redirect_uri=$REDIRECT_URI")

REFRESH_TOKEN=$(echo "$TOKEN_RESPONSE" | jq -r '.refresh_token // empty')
ACCESS_TOKEN=$(echo "$TOKEN_RESPONSE" | jq -r '.access_token // empty')
TOKEN_ERR=$(echo "$TOKEN_RESPONSE" | jq -r '.error // empty')

if [ -n "$TOKEN_ERR" ] || [ -z "$REFRESH_TOKEN" ]; then
    echo "ERROR: token exchange falló." >&2
    echo "Response: $TOKEN_RESPONSE" >&2
    exit 1
fi

# ─── Guardar refresh_token en Keychain ───
# Borramos el item previo si existe (idempotente).
security delete-generic-password -s rufino-spotify-refresh-token -a val >/dev/null 2>&1 || true
security add-generic-password -s rufino-spotify-refresh-token -a val -w "$REFRESH_TOKEN"

# Smoke-test el access_token: GET /me para confirmar que la auth funciona.
ME_JSON=$(curl -s -H "Authorization: Bearer $ACCESS_TOKEN" "https://api.spotify.com/v1/me")
DISPLAY=$(echo "$ME_JSON" | jq -r '.display_name // .id // "(unknown)"')

cat <<EOF
─────────────────────────────────────────────────────────────
Listo. Refresh token guardado en Keychain:

  Service: rufino-spotify-refresh-token
  Account: val

Autenticado como: $DISPLAY

A partir de ahora el cron rufino-ingest-spotify puede correr solo.
Para probarlo manualmente:

  RUFINO_VAULT_PATH=/Users/val/Files/vaultlentino \\
    ~/.claude/scripts/rufino-ingest-spotify.sh

─────────────────────────────────────────────────────────────
EOF
