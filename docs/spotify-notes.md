# Spotify ingestor — notas operativas

## Setup OAuth (one-time, manual)

A diferencia de GitHub/Chrome/Screen Time/Calendar, Spotify exige OAuth user-flow (no client credentials) porque `/me/player/recently-played` requiere scope `user-read-recently-played`. Val tiene que correr el bootstrap **una vez** para autorizar la app y persistir un refresh token.

### Paso 1: registrar Redirect URI en la app de Spotify

En `https://developer.spotify.com/dashboard`:

1. Entrar a la app de Rufino (la misma cuyas credenciales ya están en Keychain).
2. Click **Edit settings**.
3. En **Redirect URIs**, agregar:

   ```
   http://localhost:8765/callback
   ```

   Exactly así — sin trailing slash, sin https, puerto 8765.

4. **Save**.

Sin este paso, Spotify rechaza el flow con `INVALID_CLIENT: Invalid redirect URI`.

### Paso 2: correr el bootstrap

```bash
~/.claude/scripts/setup-spotify-auth.sh
```

El script:

1. Lee `rufino-spotify-client-id` y `rufino-spotify-client-secret` de Keychain.
2. Levanta un mini HTTP server en `localhost:8765` con `nc -l` (single-shot listener).
3. Abre `https://accounts.spotify.com/authorize?...` en el browser.
4. Val autoriza → Spotify redirige a `http://localhost:8765/callback?code=XXX&state=YYY`.
5. `nc` captura la request line, parseamos `code` y `state` del query.
6. Validamos CSRF (`state` matchea), después POST a `/api/token` con `grant_type=authorization_code`.
7. Guardamos el `refresh_token` resultante en Keychain como `rufino-spotify-refresh-token` / account `val`.

Confirmación esperada al final:

```
Listo. Refresh token guardado en Keychain:
  Service: rufino-spotify-refresh-token
  Account: val
Autenticado como: <Val display name>
```

Si algo falla (puerto ocupado, state mismatch, error de Spotify), el script aborta con un mensaje claro.

## Frecuencia y target

- Cron: domingos 04:30 (Weekday=0 en launchd).
- Procesa la **semana ISO anterior**: `date -v-7d +%G-W%V`.
- Override manual: `RUFINO_SPOTIFY_FORCE_WEEK=2026-W19 ~/.claude/scripts/rufino-ingest-spotify.sh`.

## Limitación de la API

El endpoint `GET /me/player/recently-played` devuelve sólo los últimos **50 tracks** (max ~24h hacia atrás). Si el cron corre sólo el domingo, capturamos el snapshot del weekend, no la semana completa.

**Mitigación parcial**: el script acumula tracks por semana en `${VAULT_PATH}/spotify/raw/<YYYY-WW>.json` usando el cursor `played_at` persistido en `${VAULT_PATH}/spotify/.state`. Cada corrida hace merge dedup por `played_at + track_id`.

**Para cobertura más rica**: cambiar el cron a daily (Hour=4 Minute=30, sin Weekday). El prompt ya soporta cobertura parcial sin reescribir lógica.

## Token rotation

Spotify a veces rota el refresh token en la response del refresh flow. El script detecta el caso y re-persiste el nuevo refresh_token en Keychain automáticamente. Si el refresh token se revoca (Val revoca acceso desde su cuenta o expira por inactividad), el cron va a fallar con `invalid_grant`. Fix: re-correr `setup-spotify-auth.sh`.

## Output esperado por semana

- 1 fact summary: `spotify-summary-<YYYY-WW>` (siempre, si hubo activity).
- 0–5 facts top-artist: `spotify-top-artist-<artist-slug>-<YYYY-WW>` (>= 2 plays).
- 0–10 facts track-recurrent: `spotify-track-recurrent-<artist>-<track>-<YYYY-WW>` (>= 5 plays).

Tracks con 1 sola play viven sólo en el raw, no se promueven a facts.

## Credenciales en Keychain

| Service | Account | Cuándo se setea |
|---------|---------|-----------------|
| `rufino-spotify-client-id` | `val` | Manual, al crear la app en dashboard |
| `rufino-spotify-client-secret` | `val` | Manual, al crear la app en dashboard |
| `rufino-spotify-refresh-token` | `val` | Auto, por `setup-spotify-auth.sh` |

Para inspeccionar:

```bash
security find-generic-password -s rufino-spotify-refresh-token -a val -w
```

Para borrar (forzar re-bootstrap):

```bash
security delete-generic-password -s rufino-spotify-refresh-token -a val
```
