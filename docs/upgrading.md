# Upgrading

Cómo upgrade el framework, cómo funciona el versionado, cómo escribir migrations, y cómo hacer rollback.

## El flow normal

```bash
cd ~/rufino-framework
git pull
./upgrade.sh
```

Eso es todo en el caso feliz.

Lo que pasa adentro:

1. Lee la versión instalada de `~/.rufino/version` (texto plano)
2. Lee la versión target de `rufino version` (que viene del binario pipx — declarado en `src/rufino/version.py:VERSION`)
3. Si son iguales: `Already at <X>. Nothing to do.` y sale
4. Si la instalada es **mayor** que la target: refuse, exit 1 (downgrade). Override con `RUFINO_FORCE=1`
5. Si la instalada es menor: procede
6. Hace backup de `~/.rufino/` en `~/.rufino/backups/<YYYYMMDD-HHMMSS>/`
7. Reinstala el package con `pipx reinstall rufino-framework` (o `pipx install -e $REPO_DIR` si no estaba)
8. Itera `migrations/*.sh` en orden lexicográfico, ejecutando las que no estén en `~/.rufino/applied-migrations`
9. Actualiza `~/.rufino/version` con la target

## Versionado

El framework usa **semver-ish** (`MAJOR.MINOR.PATCH`):

| Cambio | Bump |
|---|---|
| Bug fix sin cambios de API | PATCH (`0.0.2` → `0.0.3`) |
| Feature nueva backwards-compatible | MINOR (`0.0.2` → `0.1.0`) |
| Breaking change | MAJOR (`0.x.y` → `1.0.0`) |

La fuente de verdad de la versión es `src/rufino/version.py:VERSION`. **Hay que bumpear DOS lugares en cada release:**

1. `src/rufino/version.py:VERSION = "0.0.3"`
2. `pyproject.toml:version = "0.0.3"`

Si solo bumpeás uno, hay drift entre lo que dice `pip show` y lo que dice `rufino version`. El upgrade del framework usa el segundo, así que olvidarse del primero no rompe usuarios — pero confunde debugging.

### Cuándo bumpear

**Bug fix en un primitive** sin cambios de API:

```bash
# editá código + tests
git commit -m "fix(process): handle CRLF in frontmatter"
# bumpeá version PATCH
git commit -m "chore: bump version 0.0.2 → 0.0.3"
git tag v0.0.3
git push --tags
```

**Feature nueva backwards-compatible** (ej: nuevo channel en Output):

```bash
git commit -m "feat(output): add slack:// channel"
# bumpeá MINOR
git commit -m "chore: bump version 0.0.3 → 0.1.0"
git tag v0.1.0
git push --tags
```

**Breaking change** (ej: cambia el schema de un manifest):

- Necesitás una migration que convierta vault state viejo al schema nuevo
- Bumpeá MAJOR
- Documentá explícitamente el breaking change en el commit / changelog

## Migrations

Bash scripts en `migrations/` que aplican cambios al state del framework cuando hay un upgrade.

### Convenciones

- **Nombre:** `<from>-to-<to>.sh` — ej: `0.0.2-to-0.0.3.sh`
- **Orden de ejecución:** lexicográfico. Si tenés varias migrations apilando, nombralas con padding semver-friendly (`0.0.10` viene después de `0.0.9` con sort -V; con sort lexicográfico clásico, podés necesitar `0.0.02`, `0.0.10`, etc.). En la práctica el padding rara vez es necesario para semver normal.
- **Idempotencia obligatoria.** El upgrade puede reintentar después de fallar a mitad. Tu migration tiene que poder correr 2 veces y dar el mismo resultado.
- **Se trackea aplicada en** `~/.rufino/applied-migrations` — un filename por línea. Si falla a mitad y el upgrade aborta, el nombre **no** se agrega → el próximo intento la re-corre.
- **Variables disponibles:** `$RUFINO_HOME` (export que `upgrade.sh` hace antes de invocarla).
- **No pueden importar el código de Rufino** (la migration corre **contra el código nuevo** — el `pipx reinstall` ya pasó — pero las migrations no acceden al venv pipx). Lee state files directo de disco, o transformá lazy al próximo run normal.

### Skeleton

```bash
#!/usr/bin/env bash
# migrations/0.0.2-to-0.0.3.sh
# Convert old state/cursor.json format to new format with explicit timestamp.

set -euo pipefail

CURSOR_DIR="$RUFINO_HOME/state"

for cursor_file in "$CURSOR_DIR"/*/cursor.json; do
    [ -f "$cursor_file" ] || continue

    # Idempotency: skip if already migrated (presence of new field)
    if jq -e '.timestamp' "$cursor_file" >/dev/null 2>&1; then
        echo "    skip $cursor_file (already migrated)"
        continue
    fi

    tmp="$(mktemp)"
    jq '. + {timestamp: (now | tostring)}' "$cursor_file" > "$tmp"
    mv "$tmp" "$cursor_file"
    echo "    migrated $cursor_file"
done
```

### Patrones comunes

**Renombrar una key en un JSON state file:**

```bash
for f in "$RUFINO_HOME/state"/*.json; do
    if jq -e '.old_key' "$f" >/dev/null 2>&1; then
        tmp="$(mktemp)"
        jq '. | .new_key = .old_key | del(.old_key)' "$f" > "$tmp"
        mv "$tmp" "$f"
    fi
done
```

**Agregar un dir nuevo a `~/.rufino/`:**

```bash
mkdir -p "$RUFINO_HOME/new_subdir"   # idempotente
```

**Borrar un dir / archivo obsoleto:**

```bash
rm -rf "$RUFINO_HOME/deprecated_dir"   # idempotente
```

**Convertir un manifest viejo a nuevo schema:**

```bash
for manifest in "$RUFINO_HOME"/adapters/*/*/manifest.yaml; do
    # python3 in-script (instalado en el sistema, no en el venv pipx)
    python3 - "$manifest" <<'PY'
import sys, yaml
path = sys.argv[1]
data = yaml.safe_load(open(path))
if 'new_field' in data:
    sys.exit(0)  # idempotency
data['new_field'] = data.pop('old_field', 'default')
with open(path, 'w') as f:
    yaml.safe_dump(data, f)
PY
done
```

### Testing una migration

```bash
# Backup del state actual
cp -a ~/.rufino ~/.rufino.test-backup

# Forzar re-run (sacar de applied-migrations)
sed -i '' '/0.0.2-to-0.0.3.sh/d' ~/.rufino/applied-migrations

# Correr la migration en aislado
RUFINO_HOME=~/.rufino bash migrations/0.0.2-to-0.0.3.sh

# Verificar el resultado
ls ~/.rufino/state/...

# Si rompió algo, restore
rm -rf ~/.rufino && mv ~/.rufino.test-backup ~/.rufino
```

## Backups automáticos

Cada upgrade hace backup de `~/.rufino/` (excepto `backups/` mismo, para evitar recursión) antes de aplicar nada:

```
~/.rufino/backups/20260517-143022/
├── version
├── applied-migrations
├── state/
└── adapters/
```

`cp -a` se usa para preservar symlinks, permisos y mtimes. No incluye `backups/` para evitar recursión exponencial.

### Limpiar backups viejos

No hay cleanup automático. Si querés borrar backups viejos:

```bash
# Listar
ls -lt ~/.rufino/backups/

# Borrar los anteriores a una fecha
find ~/.rufino/backups/ -maxdepth 1 -mindepth 1 -type d -mtime +30 -exec rm -rf {} +
```

## Rollback manual

Si un upgrade rompió algo, restaurá el backup más reciente:

```bash
# Identificá el último backup
LAST=$(ls -t ~/.rufino/backups/ | head -n1)
echo "Restoring from: $LAST"

# Limpia state actual (NO toca backups/)
find ~/.rufino -maxdepth 1 -mindepth 1 ! -name backups -exec rm -rf {} +

# Restaurá
cp -a ~/.rufino/backups/"$LAST"/* ~/.rufino/

# Verificá
cat ~/.rufino/version
```

Si el upgrade además bumpeó el code (`pipx reinstall` corrió OK pero las migrations rompieron), considerá downgradear el package:

```bash
cd ~/rufino-framework
git checkout v0.0.2          # o el tag de la versión que funcionaba
RUFINO_FORCE=1 ./upgrade.sh   # acepta el downgrade
```

(Esto requiere que las migrations sean reversibles — en la práctica, hacé el rollback de state primero.)

## Cuándo hacer un release

El proceso recomendado:

1. **Branch.** Cualquier cambio relevante en una branch `feat/<nombre>` o `fix/<nombre>`. Nunca en `main` directo.
2. **Tests verdes.** `pytest` debe pasar localmente (`.venv/bin/python -m pytest`).
3. **Code review.** Si es cambio grande (>30 files, breaking change, etc.), el patrón del proyecto es correr 5 agentes paralelos de review pre-merge.
4. **Bump version.** En el mismo PR o en un commit separado `chore: bump version <old> → <new>` que toca `version.py` + `pyproject.toml`.
5. **Migrations.** Si el cambio requiere transformación de state, agregá la migration en `migrations/`.
6. **Merge a main** con `git merge --no-ff feat/<branch>`.
7. **Tag.** `git tag v0.0.3 && git push --tags`.
8. **Borrar branch local.** `git branch -d feat/<branch>`.

Una vez taggeado, los usuarios con `git pull && ./upgrade.sh` reciben el cambio automáticamente.

## Política de breaking changes

Hasta que el framework alcance v1.0:

- Cambios breaking son aceptables — el framework está en v0.x, los usuarios saben que las APIs pueden mover.
- **Pero** cada breaking change tiene que venir con su migration. Romper sin migration = inaceptable.
- Documentá el breaking change en el commit message + changelog (cuando exista) + en el output del wizard al re-bootstrappear.

Desde v1.0 en adelante:

- Breaking changes solo en major bumps.
- Compatibilidad de helper API se mantiene **2 versiones** (un adapter generado con `helpers/v1` sigue funcionando bajo `helpers/v2` con deprecation warning; bajo `helpers/v3` rompe).

## La trampa de no bumpear

Si modificás código sin bumpear `src/rufino/version.py`, los usuarios que hagan `git pull && ./upgrade.sh` van a ver:

```
==> Already at 0.0.2. Nothing to do.
```

Y no se les aplica nada — porque el upgrade compara versión texto contra texto. El binario `pipx` quedó con código viejo y `~/.rufino/version` también, así que el upgrade pasa sin hacer nada.

**Regla: cualquier cambio que necesite llegar a usuarios via upgrade requiere bump de versión.**

Si te olvidaste el bump, podés rescatar con:

```bash
# Forzar reinstall sin bumpear
pipx reinstall rufino-framework
```

Pero las migrations no se aplican (porque `version` matcheada). Si necesitabas correr una migration, ahora estás obligado a bumpear igual.
