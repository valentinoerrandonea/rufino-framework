# Getting started

Instalación + primer bootstrap, paso a paso, con qué esperar en cada momento.

## Pre-requisitos

| Requisito | Cómo chequear | Cómo instalar |
|---|---|---|
| **macOS o Linux** | `uname -s` | (no aplica) |
| **Python ≥ 3.11** | `python3 --version` | `brew install python@3.11` o el package manager del distro |
| **pipx** | `pipx --version` | macOS: `brew install pipx && pipx ensurepath`. Linux: `python3 -m pip install --user pipx && python3 -m pipx ensurepath` |
| **Claude Code CLI** | `claude --version` | Ver [docs oficiales de Claude Code](https://docs.claude.com/claude-code) |
| **jq** (recomendado) | `jq --version` | `brew install jq` o el package manager |

Si te falta algo, instalalo antes — el `install.sh` te avisa cuál falta y aborta.

## Instalación

```bash
git clone https://github.com/<owner>/rufino-framework.git ~/rufino-framework
cd ~/rufino-framework
./install.sh
```

Lo que pasa adentro (siete pasos, ver `install.sh` comentado):

1. Chequea `python3 --version` ≥ 3.11
2. Chequea `pipx --version`; si falta, imprime instrucciones y aborta
3. Instala el package con `pipx install -e $REPO_DIR` (idempotente — si ya estaba, hace `pipx reinstall`)
4. Resuelve el bin dir de pipx (`pipx environment --value PIPX_BIN_DIR`)
5. Si tu `$SHELL` es bash o zsh, agrega `export PATH="$BIN_DIR:$PATH"  # rufino-framework` a tu rc; idempotente (busca el marker comment)
6. Crea `~/.rufino/{state,backups,adapters/{ingest,process,output,memory_loop}}/` y escribe `~/.rufino/version`
7. Si exportaste `RUFINO_VAULT` apuntando a una carpeta existente y `jq` está instalado, registra `ask-rufino-<slug>` (slug = basename del vault) en `~/.claude.json`. Si no, lo registra el wizard al cierre del bootstrap. Cada vault es su propia entry MCP — múltiples vaults coexisten sin pisarse.

Al final imprime:

```
==> Done.

Listo. Para empezar, abrí una shell nueva (o source ~/.zshrc) y corré:
    rufino bootstrap
```

**Importante:** abrí una shell nueva (o hacé `source` de tu `.zshrc`/`.bashrc`) **antes** de correr `rufino bootstrap` — si no, el `$PATH` actualizado no está cargado y tu shell no encuentra el binario.

Verificá:

```bash
which rufino       # → /Users/<vos>/.local/bin/rufino (o equivalente de pipx)
rufino version     # → 0.1.0
```

> `process-batch` requiere `mammoth` y `python-pptx` (declarados en
> `pyproject.toml`). Si te aparece `ModuleNotFoundError`, reinstalá con
> `./install.sh` o `pipx install -e .`.

## Primer bootstrap

```bash
rufino bootstrap
```

Esto lanza `claude -p <system-prompt>` con un toolset restringido (`Read`, `Write`, `Bash(rufino materialize:*)`, `Bash(rufino query:*)`). Claude arranca con un system prompt que lo configura como **el wizard**: lenguaje user, checklist interno de objetivos, catálogo de 6 patterns conocidos, reglas operativas de conversación.

### Conversación esperada

Claude va a abrir con algo como:

> *Hola, vamos a armar tu sistema. Contame qué problema querés resolver — ¿qué te gustaría tener centralizado en un solo lugar?*

A partir de ahí va preguntando para llenar internamente esta checklist (que vos no ves):

- [ ] Vertical identificado
- [ ] Patrón(es) seleccionado(s) del catálogo
- [ ] Entidades centrales definidas
- [ ] Fuentes identificadas
- [ ] Política de processing
- [ ] Outputs definidos
- [ ] Vocabulary del vertical
- [ ] Usuario confirmó el sistema

**Reglas de la conversación** (Claude las aplica solo, vos no las invocás):

- Si tu respuesta es ambigua, repregunta con opciones concretas (*"¿es más A o más B?"*) — no con open questions.
- Si no sabés algo, te da ejemplos concretos del vertical inferido.
- No usa jerga técnica. Si vos la usás, la traduce a algo concreto.
- No pregunta de más cuando ya tiene info suficiente.
- Si decís *"para"* — para limpio, sin guardar nada, sin acusar.

Detalle del wizard: [`wizard.md`](wizard.md).

### El big bang (resumen final)

Cuando Claude tiene info suficiente, te muestra el resumen en lenguaje natural — algo como:

```
OK, te resumo lo que vamos a armar:

📒 Tu vault va a tener:
  - Apuntes organizados por materia
  - Papers archivados por área
  - Profesores como contactos
  - Conceptos clave (regresión, redes bayesianas, etc.) con su propia página
    cuando aparezcan seguido

🔌 Va a conectarse con:
  - Tu carpeta de Drive donde tirás PDFs
  - Tu calendario (para detectar fechas de examen)

⚡ Cuando agregues algo nuevo (PDF, nota, lo que sea):
  - Lo organiza por materia automáticamente
  - Lo enriquece (resumen, contexto, ideas conectadas)
  - Detecta los temas principales y los conecta con apuntes previos vía links
  - Si menciona un profe nuevo, lo registra como contacto
  - Si no está seguro de algo, te pregunta — no inventa

💬 Mientras conversás conmigo en Claude Code:
  - Voy guardando lo valioso al vault sin que te acuerdes
  - Al cerrar la sesión te pregunto si hay más para guardar

🔍 Para encontrar cosas después:
  - Le preguntás al vault en lenguaje natural
  - O navegás las conexiones como grafo

🤖 Desde cualquier conversación con Claude Code:
  - Le preguntás a Claude sobre tu vault y te contesta
    (estás laburando en otro proyecto y querés saber qué viste sobre X
    en la cursada — preguntás directo, sin abrir el vault)

📬 Vas a recibir:
  - Resumen los viernes con lo que viste esa semana
  - Aviso 24h antes de cada examen
  - Tu "bio académica" del mes (qué materias avanzaste, qué temas estudiaste)

¿Dale así, o algo no encaja?
```

Si decís **dale**:

1. Claude llama a `rufino materialize --spec /tmp/wizard-spec.json --vault <X> --claude-home ~/.claude --state-dir ~/.rufino/state`
2. La materialización es transaccional: el vault, los adapters, las reglas del memory loop y el registro del MCP server se aplican en una operación que registra cada paso en el transaction log
3. Si algo falla en cualquier paso → rollback completo, vault queda como estaba
4. Si todo OK → te dice: *"Listo, tu sistema está armado. Tirá un PDF a `~/<vault>/inbox/` para probarlo."*

Si decís **no encaja**: Claude te pregunta qué cambiar y vuelve al loop conversacional.

### Qué queda materializado

Después de un bootstrap exitoso, tu disco tiene:

**Tu vault** (donde vos elijas):

```
~/<vault>/
├── perfil.md                # de quién es el vault, qué hace
├── README.md                # auto-generado, en lenguaje user
├── inbox/                   # tirá acá lo que quieras procesar
├── <carpetas-de-tu-vertical>/   # ej: apuntes/, papers/, profesores/
├── _meta/                   # indices, embeddings.sqlite
└── questions/               # Q&A pendientes (vacío al principio)
```

**`~/.rufino/`** (state del framework):

```
~/.rufino/
├── version                  # 0.1.0
├── applied-migrations       # vacío al principio
├── state/                   # cursores de Ingest, dedup, qa state
├── backups/                 # snapshots pre-upgrade
└── adapters/
    ├── ingest/<adapters-tuyos>/
    ├── process/<adapters-tuyos>/
    ├── output/<adapters-tuyos>/
    └── memory_loop/<adapter-tuyo>/
```

**`~/.claude/`** (memory loop instalado):

```
~/.claude/
├── rules/common/<vertical>-rules.md       # reglas de tu vertical
├── hooks/<vertical>-init.sh               # carga reglas al iniciar sesión
└── commands/...
```

**`~/.claude.json`** (MCP server registrado):

```json
{
  "mcpServers": {
    "ask-rufino-<slug>": {
      "command": "/Users/<vos>/.local/bin/rufino",
      "args": ["mcp-server", "--vault", "/Users/<vos>/<vault>"]
    }
  }
}
```

`<slug>` es el basename del vault normalizado (lowercase, sin caracteres especiales). Si tenés dos vaults `~/facultad` y `~/work`, vas a ver dos entries: `ask-rufino-facultad` y `ask-rufino-work`.

### Si algo sale mal

Si la materialización falla, el transaction log se ejecuta en reversa — tu disco queda como estaba antes de `dale`. El error queda en stderr; en muchos casos Claude te lo lee y te ofrece reintentar.

Errores típicos:
- **`spec validation failed`** — el wizard generó un spec inválido. Reportá el caso (es un bug del wizard).
- **`Vault path already exists and is not empty`** — apuntaste el vault a una carpeta con archivos. Elegí otra o vaciá la actual.
- **`Could not register MCP server: jq not installed`** — instalá `jq` y registralo manualmente, o re-corré el wizard.

Más en [`troubleshooting.md`](troubleshooting.md).

## Primer uso del vault

### Tirar un PDF

```bash
cp ~/Downloads/clase3-regresion-logistica.pdf ~/facultad/inbox/
```

Si el wizard armó un `process-apunte-clase` con trigger `immediate`, el PDF se va a procesar al toque (vía file watcher o cron — depende cómo lo materialicen los adapters). Vas a ver aparecer:

```
~/facultad/apuntes/<materia>/2026-05-17-regresion-logistica.md
```

Con frontmatter + body augmentado + wikilinks + triples.

### Si Claude no está seguro de algo

Si el LLM detecta ambigüedad (ej: "no sé de qué materia es este apunte"), dispara una Q&A:

```
~/facultad/questions/2026-05-17-materia-clase3.md
```

Vos editás el frontmatter `answer:` con tu respuesta. La próxima vez que corra `rufino qa-poll`, el worker detecta la respuesta, completa el procesamiento, y mueve la question a `questions/answered/`.

### Consultar el vault desde otra conversación de Claude

Andá a cualquier proyecto:

```bash
cd ~/laburo/proyecto-X/
claude
```

Y preguntá:

> *Qué me dijo el profe Méndez sobre cross-entropy en mi cursada?*

Claude detecta que la pregunta es sobre tu vault, llama al MCP `ask-rufino-facultad`, busca, y te contesta con las menciones reales. Nunca abriste `~/facultad/`.

### Memory loop

Mientras conversás con Claude Code dentro del vault (o cualquier proyecto si la regla del memory loop está activa), Claude detecta cosas valiosas y propone guardarlas. Al cierre de la sesión te pregunta si hay más para guardar.

## Próximos pasos

- **Aprender la CLI:** [`cli-reference.md`](cli-reference.md)
- **Entender el vocabulario:** [`concepts.md`](concepts.md)
- **Entender qué hace cada primitive:** [`primitives/`](primitives/)
- **Escribir tu propio adapter:** [`writing-adapters.md`](writing-adapters.md)
