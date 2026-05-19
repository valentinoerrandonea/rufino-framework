# Troubleshooting

Problemas comunes y cómo resolverlos.

## Instalación

### `python3 not found`

```
ERROR: python3 not found. Install Python 3.11+ first.
```

Tu sistema no tiene `python3` o no está en `$PATH`.

- **macOS:** `brew install python@3.11`
- **Linux (Debian/Ubuntu):** `sudo apt install python3 python3-venv`
- **Linux (Arch/Omarchy):** `sudo pacman -S python`

Después de instalar, abrí una shell nueva y volvé a correr `./install.sh`.

### `pipx not found`

```
ERROR: pipx not found. Install it first:
  macOS:  brew install pipx && pipx ensurepath
  Linux:  python3 -m pip install --user pipx && python3 -m pipx ensurepath
```

Es la dependencia más común que falta. Una vez instalada pipx, **abrí una shell nueva** antes de volver a correr `./install.sh` — `ensurepath` modifica el `$PATH` y necesita reload.

### `pipx install --force` falla con uv backend

```
Not removing existing venv ... was not created in this session
```

El `install.sh` ya lo maneja — detecta si el package está instalado con `pipx list --short` y usa `pipx reinstall` en vez de `pipx install --force`. Si lo ves, significa que estás corriendo `pipx install` a mano. Usá:

```bash
pipx reinstall rufino-framework
```

### `rufino: command not found` después del install

El installer agregó `export PATH="<pipx_bin>:$PATH"  # rufino-framework` a tu `.zshrc` / `.bashrc`, pero tu shell actual no lo tiene cargado.

```bash
source ~/.zshrc   # o ~/.bashrc según tu shell
# o cerrá y abrí una shell nueva
which rufino      # → debería responder ahora
```

Si después de `source` sigue sin verlo:

```bash
grep -n "rufino-framework" ~/.zshrc       # confirmá que el export está
echo $PATH | tr ':' '\n' | grep -i local  # confirmá que el dir está en PATH
```

### `MCP server NOT registered — RUFINO_VAULT not set`

El installer solo registra el MCP server si exportaste `RUFINO_VAULT=<path-existente>` antes de correr `install.sh`. Si no, lo registra el wizard al cierre del bootstrap. Normalmente está OK — corré `rufino bootstrap` y el MCP queda registrado al final.

Si querés registrarlo manualmente más tarde (sin re-bootstrap):

```bash
RUFINO_VAULT=/Users/<vos>/<vault> ./install.sh
```

(Es idempotente — re-correr es seguro.)

### `jq: command not found`

```
WARN: jq not installed — skipping MCP registration.
```

El installer usa `jq` para editar `~/.claude.json` de forma segura. Sin `jq` no puede registrar el MCP automáticamente.

```bash
brew install jq        # macOS
sudo apt install jq    # Debian/Ubuntu
```

Después re-correr el installer (idempotente).

---

## Wizard

### `Error: 'claude' CLI no encontrado en PATH.`

`rufino bootstrap` requiere Claude Code CLI. Instalalo siguiendo [docs.claude.com/claude-code](https://docs.claude.com/claude-code), confirmá con `claude --version`, y reintentá.

### El wizard usa jerga técnica

No debería. Si ves a Claude usando palabras como *"manifest", "adapter", "primitive", "frontmatter"* con vos, hay drift del system prompt. Reportalo — el prompt está en `src/rufino/wizard/system_prompt_assembler.py` y `language_rules.md`. Probablemente falte una traducción.

Inspeccioná el prompt:

```bash
rufino bootstrap --dry-run | less
```

### El wizard no entiende mi caso de uso

Después de 2-3 preguntas sin matching pattern claro, Claude debería **caer al modo fallback** (construir desde primitives básicas: memory loop + 1-2 Process + Output digest). Si no lo hace y se queda en loop preguntando, terminá la sesión y reportalo — es un edge case del wizard.

Workaround temporal: armá manualmente una `WizardSpec` JSON usando los ejemplos en [`writing-adapters.md`](writing-adapters.md), y corré:

```bash
rufino materialize --spec spec.json --vault <X> --claude-home ~/.claude --state-dir ~/.rufino/state
```

### Cancelé el wizard a mitad y no me deja retomar

Esto es a propósito — el wizard es greenfield siempre, sin resume. Volvé a correr `rufino bootstrap` desde cero. Como no se guarda nada hasta el big bang, no perdiste nada del lado del disco.

### `Spec validation failed: ...`

El wizard generó una `WizardSpec` inválida. Eso **es un bug del wizard**, no algo que vos puedas arreglar editando. Reportalo con:

```bash
cat /tmp/<spec-file>.json     # el path lo imprime el error
rufino bootstrap --dry-run > /tmp/wizard-prompt.txt
```

Como workaround: editá el JSON a mano para hacerlo válido y corré `rufino materialize` directo.

---

## Materialización

### `Vault path already exists and is not empty`

Apuntaste el vault a una carpeta que ya tiene archivos. El framework no sobrescribe vaults existentes — es protección contra borrar trabajo previo.

Opciones:

- Elegí otra carpeta vacía para el vault.
- Mové la carpeta actual a backup y reintentá.
- Si la carpeta tiene solo archivos de prueba que querés eliminar:
  ```bash
  rm -rf <vault-path>
  rufino bootstrap     # de nuevo
  ```

### Rollback ejecutado pero quedaron archivos

El [transaction log](runtime.md#transaction-log) ejecuta el inverso de cada operación registrada. Si hay archivos huérfanos después de un rollback, puede ser:

- Una operación que tocó disco **sin pasar** por `apply_and_log` (bug del framework — reportalo).
- Un símbolo creado a mano antes de la materialización que el rollback no toca a propósito (preservation policy).

Inspeccioná el tx log para ver qué pasó:

```bash
ls ~/.claude/tx/                    # logs de install-memory-loop
ls ~/.rufino/state/tx/              # logs de materialize (si los hay)
```

### MCP no aparece en Claude Code después del wizard

Verificá (sustituyendo `<slug>` por el basename de tu vault, normalizado a lowercase/kebab):

```bash
jq '.mcpServers' ~/.claude.json   # lista todos los servers; buscá ask-rufino-*
jq '.mcpServers["ask-rufino-<slug>"]' ~/.claude.json
```

Debería responder con `{"command": "...", "args": ["mcp-server", "--vault", "..."]}`.

Si no aparece, el wizard no llegó a registrarlo. Causas posibles:

- `jq` no estaba instalado al momento de materializar (instalá y volvé a correr `rufino materialize` con el spec que el wizard generó — debería estar en `/tmp/`).
- El proceso terminó abruptamente.

Para registrarlo a mano (slug derivado del basename del vault):

```bash
VAULT=/path/to/your/vault
SLUG=$(basename "$VAULT" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//')
jq --arg vault "$VAULT" --arg name "ask-rufino-$SLUG" \
   '.mcpServers[$name] = {
     command: "rufino",
     args: ["mcp-server", "--vault", $vault]
   }' ~/.claude.json > /tmp/c.json && mv /tmp/c.json ~/.claude.json
```

Después abrí una sesión nueva de Claude Code — el MCP se carga al startup.

---

## Runtime / uso

### `rufino query --mode hybrid` exits 2

```
Error: --mode=hybrid requires a real embedder; only --mode=lexical is wired in this release
```

El embedder real (Ollama) todavía no está integrado. Usá `--mode lexical`:

```bash
rufino query "tu busqueda" --vault <X> --mode lexical
```

Para semántica real, esperá la integración del embedder (plan referenciado en el roadmap).

### `rufino process --mode full` exits 2

El single-note `--mode full` queda diferido. Para procesar en lote (ZIP o
directorio con múltiples docs) usá `rufino process-batch`. Para registrar
notas sin LLM call, usá `--mode light`.

### Una nota se procesó mal

Si Process le puso mal el frontmatter o triples inválidos:

- Editala a mano. El vault es markdown plano — todo es auditable.
- Corré `rufino process <nota> --mode lint --vault <X>` para validar.
- Si el problema es sistémico (todas las notas de ese tipo salen mal), el adapter Process tiene un prompt mal redactado — editá `~/.rufino/adapters/process/<adapter_name>/prompt.md`.

### Un Ingest no avanza

```bash
rufino ingest <adapter_dir> --vault <X> --state-dir ~/.rufino/state
# adapter=<name> emitted=0 skipped=0 errors=3
```

Si `errors > 0`, el cursor **no avanza** (idempotencia). Mirá los errores en stderr, corregí la causa, y volvé a correr — el adapter va a re-procesar el mismo rango.

Si `emitted=0 skipped=0 errors=0`, no hay data nueva desde el último cursor. Esperado.

### Q&A pendientes que no se dispatchan

```bash
rufino qa-poll --vault <X> --state-dir ~/.rufino/state
# dispatched=0
```

`qa-poll` resuelve preguntas originadas en `process-batch`: detecta
`answer:` no vacíos en `<vault>/questions/`, retoma el worker con la
respuesta inyectada y archiva la pregunta a `questions/answered/`. Si
`dispatched=0` y tenés `answer:` llenos, revisá que el `origin:` del
frontmatter apunte a un adapter con resumption soportada (otros adapters
todavía no la implementan).

Si necesitás cerrar manualmente una Q&A de un adapter sin resumption:

1. Editá el frontmatter de la pregunta con tu answer
2. Mové el archivo a `<vault>/questions/answered/`
3. Editá la nota original que disparó la Q&A (debería tener `status: awaiting_user_input`) y resolvela a mano

---

## Upgrade

### `ERROR: $RUFINO_HOME/version not found`

```
ERROR: /Users/<vos>/.rufino/version not found. Run ./install.sh first.
```

Estás corriendo `upgrade.sh` sin haber corrido `install.sh` antes. Hacelo:

```bash
./install.sh
```

### `Already at <version>. Nothing to do.` después de git pull

`upgrade.sh` compara `~/.rufino/version` con `rufino version` (que viene del binario instalado). Si son iguales, no hace nada.

Si vos cambiaste código sin bumpear `src/rufino/version.py`, el upgrade no lo aplica. Bumpeá la versión + `pyproject.toml` y re-corré `./upgrade.sh`.

### `refusing downgrade from X to Y`

El upgrade detecta versiones decrecientes y rechaza el downgrade por default. Si realmente querés downgradear (riesgoso — los state files pueden no ser compatibles):

```bash
RUFINO_FORCE=1 ./upgrade.sh
```

Hacé backup del vault y de `~/.rufino/` antes.

### Migration falla a mitad de upgrade

Si una migration aborta, su nombre **no** se agrega a `~/.rufino/applied-migrations`, así que la próxima corrida la reintenta (migrations deben ser idempotentes — reintentar es seguro).

Si el reintento sigue fallando, mirá:

```bash
cat ~/.rufino/applied-migrations    # ver hasta dónde llegó
ls migrations/                       # ver cuál es la que falla
```

Restaurá del backup más reciente:

```bash
ls ~/.rufino/backups/
# rm -rf ~/.rufino/state ~/.rufino/adapters ...   # cuidado!
# cp -a ~/.rufino/backups/<timestamp>/* ~/.rufino/
```

---

## Performance

### El MCP `ask-rufino-<slug>` arranca lento

Por default rebuildea índices semantic+graph al startup. En vaults grandes esto puede tomar 30s-2min. Opciones:

- Usá `--no-rebuild` al lanzar el MCP server (pero el primer arranque sí necesita `--rebuild` para popular la DB):
  ```bash
  rufino mcp-server --vault <X> --no-rebuild
  ```
- Rebuildeá manualmente cuando lo necesites:
  ```python
  from rufino.engine.query.api import QueryLayer
  ql = QueryLayer(vault_root=..., embedder=...)
  ql.rebuild_indices()
  ```

### Process se cuelga en una nota grande

El single-note Process no tiene timeout configurable. Si tenés PDFs gigantes que cuelgan el pipeline, splitealos antes de tirarlos al inbox, o esperá a la integración del sandbox con timeouts reales.

---

## Cómo reportar un bug

1. Confirmá la versión: `rufino version`
2. Capturá el error completo (stdout + stderr)
3. Adjuntá:
   - Sistema (`uname -a`)
   - Python (`python3 --version`)
   - pipx (`pipx --version`)
   - Output de `pipx list --short`
4. Si involucra el wizard, capturá el system prompt: `rufino bootstrap --dry-run > prompt.txt`
5. Si involucra materialización, adjuntá el spec (típicamente `/tmp/wizard-spec.json` — el path sale en el comando que Claude invocó)

Abrí un issue en el repo con todo lo anterior.
