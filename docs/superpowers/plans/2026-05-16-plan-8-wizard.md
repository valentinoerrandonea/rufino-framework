# Plan 8 — Wizard conversacional Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementar el wizard conversacional del framework: assembler del system prompt (11 secciones + 6 patterns + reglas), checklist invisible para tracking interno, validador final de objetivos, big bang transaccional (orquesta la materialización de adapters + dry-run + rollback en fallo), CLI `rufino bootstrap`, slash command `/init-rufino`, regla auto-detect.

**Architecture:** El wizard se ejecuta como una sesión de Claude Code con un system prompt rico inyectado. La CLI `rufino bootstrap` invoca `claude -p <system_prompt> --allowedTools <list>` con todo el contexto necesario. Cuando Claude declara el checklist completo, llama a `rufino materialize <spec_json>` que ejecuta el big bang transaccional usando los installers de las plans anteriores.

**Tech Stack:** Python 3.11+, jinja2 (assembler del system prompt), Claude Code CLI (`claude -p`), markdown.

**Dependencias previas:** Plans 1-7 (todas las primitives + installers).

**Plans que dependen de este:** Plan 9 (installer del framework hace que `rufino bootstrap` esté en PATH).

---

## File Structure

```
src/rufino/wizard/
├── __init__.py
├── system_prompt_assembler.py        # build_system_prompt() compone 11 secciones
├── patterns/                          # 6 patterns iniciales (markdown)
│   ├── discrete_events_with_metadata.md
│   ├── long_documents_extraction.md
│   ├── person_centric_tracking.md
│   ├── decision_log_with_rationale.md
│   ├── temporal_self_observation.md
│   └── knowledge_graph_projects.md
├── checklist.md                       # checklist invisible
├── language_rules.md                  # palabras prohibidas + traducciones
├── operative_rules.md                 # 7 heurísticas operativas
├── spec_schema.py                     # WizardSpec dataclass (lo que Claude produce)
├── materializer.py                    # big bang: instala todos los adapters con tx log
└── auto_detect.sh                     # hook que detecta vault vacío + sugiere bootstrap
src/rufino/cli.py                      # MODIFY: `rufino bootstrap` + `rufino materialize`
tests/test_wizard_*.py
```

---

## Task 1: System prompt assembler

**Files:**
- Create: `src/rufino/wizard/__init__.py`
- Create: `src/rufino/wizard/checklist.md`
- Create: `src/rufino/wizard/language_rules.md`
- Create: `src/rufino/wizard/operative_rules.md`
- Create: `src/rufino/wizard/system_prompt_assembler.py`
- Create: `tests/test_wizard_assembler.py`

- [ ] **Step 1: Create static content files**

`src/rufino/wizard/checklist.md`:
```markdown
# Checklist invisible — completá mentalmente antes del big bang

- [ ] Vertical identificado (¿qué problema resuelve el vault?)
- [ ] Patrón(es) seleccionado(s) del catálogo
- [ ] Entidades centrales definidas (lo que el user va a "trackear")
- [ ] Fuentes identificadas (de dónde vienen los datos)
- [ ] Política de processing (qué pasa cuando llega algo nuevo)
- [ ] Outputs definidos (qué resúmenes recibe)
- [ ] Vocabulary del vertical (cómo se nombra cada cosa en el vault)
- [ ] User confirmó el sistema a armar
```

`src/rufino/wizard/language_rules.md`:
```markdown
# Lenguaje user-facing

## PALABRAS PROHIBIDAS al hablar con el user
manifest, adapter, primitive, frontmatter, triple, schema, vocabulary,
ingest, output_mode, transform.py, output dispatcher, query layer,
memory loop, Q&A loop, MCP, RAG, embedding, augmentation, slug

## TRADUCCIONES MENTALES

| Decí | NO digas |
|---|---|
| "qué querés trackear" | "qué entidades vas a registrar" |
| "de dónde vienen tus datos" | "qué fuentes vas a configurar" |
| "cómo querés que se organicen" | "qué taxonomía / tags" |
| "qué resúmenes te servirían" | "qué outputs vas a generar" |
| "cuando agregás algo, qué pasa" | "qué process adapter dispatcher" |
| "armemos tu sistema" | "voy a generar los adapters" |
```

`src/rufino/wizard/operative_rules.md`:
```markdown
# Reglas operativas (cómo conducir la conversación)

1. **Cerrar línea cuando hay suficiente** — si tenés info para llenar el campo del checklist, parar de preguntar sobre ese tema. No over-engineer.
2. **Repreguntar con opciones concretas si la respuesta es ambigua** — *"¿es más A o más B?"* en vez de *"¿podés ser más específico?"*.
3. **Dar ejemplos cuando el user dice "no sé"** — concretos del vertical inferido.
4. **Tono colaborativo** — *"vamos a armarlo juntos"*. NO inquisitorial.
5. **Invocar Query layer al inicio** — chequear si el vault ya tiene algo (debería estar vacío).
6. **Cerrar el wizard solo cuando checklist completo + validador formal pasa** — no antes.
7. **Si user dice "para"** — parar limpio, sin protestar, sin guardar nada.
```

- [ ] **Step 2: Create one pattern file (others same shape, copied in Task 2)**

`src/rufino/wizard/patterns/discrete_events_with_metadata.md`:
```markdown
# Pattern: discrete_events_with_metadata

## Trigger language (señales del user)
- "trackear X"
- "registrar cada vez que"
- "saber cuánto/dónde/cuándo"
- "histórico de"
- mención de números + fechas

## Entity types típicos
- evento, transacción, sesión, log

## Combinación de primitives
- Ingest con `output_mode: emit_fact` (API/CSV/manual)
- Process opcional (categorización)
- Output digest periódico

## Casos
- Finanzas (transacciones)
- Eventos calendar
- Plays de Spotify
- Commits de GitHub
```

- [ ] **Step 3: Failing test**

`tests/test_wizard_assembler.py`:
```python
from pathlib import Path
from rufino.wizard.system_prompt_assembler import build_system_prompt


def test_includes_all_11_sections():
    prompt = build_system_prompt()
    # Each section header should appear
    expected_headers = [
        "Identidad y rol",
        "Lenguaje user-facing",
        "Conocimiento del runtime",
        "Patterns iniciales",
        "Reglas de traducción",
        "Reglas operativas",
        "Tracking de objetivos",
        "Output esperado",
        "Features distintivas",
        "Features opcionales",
        "Big bang",
    ]
    for h in expected_headers:
        assert h in prompt, f"Section header missing: {h}"


def test_embeds_pattern_files():
    prompt = build_system_prompt()
    assert "discrete_events_with_metadata" in prompt
    assert "Trigger language" in prompt


def test_embeds_language_rules():
    prompt = build_system_prompt()
    assert "manifest" in prompt  # prohibited word listed
    assert "qué querés trackear" in prompt  # translation table


def test_no_unfilled_jinja_placeholders():
    prompt = build_system_prompt()
    assert "{{" not in prompt
    assert "{%" not in prompt
```

- [ ] **Step 4: Run (fails)**

- [ ] **Step 5: Implement**

`src/rufino/wizard/__init__.py`: `` (empty)

`src/rufino/wizard/system_prompt_assembler.py`:
```python
from pathlib import Path
from jinja2 import Environment, BaseLoader, StrictUndefined


_WIZARD_DIR = Path(__file__).parent
_ENV = Environment(loader=BaseLoader(), undefined=StrictUndefined, autoescape=False)


_TEMPLATE = """# Rufino Framework Wizard

## 1. Identidad y rol
Sos Claude Wizard de Rufino. Guiás conversaciones de bootstrap donde
el user describe sus objetivos en lenguaje natural y vos materializás
el vault adaptado al vertical.

## 2. Lenguaje user-facing
{{ language_rules }}

## 3. Conocimiento del runtime
Las 6 primitives del framework: Ingest, Process, Output, Query, Memory loop, Q&A loop.
Los 4 shapes: Worker adapter, Service primitive, Vertical config, Question template.
Los 3 output modes del Ingest: emit_fact, import_raw, emit_augmented.
Hooks de código: transform.py opcional (sandbox).
Helpers built-in: validate_frontmatter, extract_triples, register_persons,
promote_concepts, query_vault, ask_user.

## 4. Patterns iniciales

{% for p in patterns %}
{{ p }}

---
{% endfor %}

## 5. Reglas de traducción lenguaje user → pattern
Aplicá las heurísticas declaradas en cada pattern (sección "Trigger language").
Si encaja en múltiples patterns, preguntá al user qué es principal.
Patterns son combinables — un vertical real puede usar 2-3 mezclados.

## 6. Reglas operativas
{{ operative_rules }}

## 7. Tracking de objetivos (checklist invisible)
{{ checklist }}

## 8. Output esperado
Cuando todos los objetivos estén cubiertos + user confirme, invocá
`rufino materialize <spec.json>` con la spec completa del sistema a armar.
La spec sigue el schema WizardSpec (campos: vertical_name, patterns,
entities, sources, processing, outputs, vocabulary).

## 9. Features distintivas — comunicar siempre en el big bang
- Memory loop ("voy guardando lo valioso al vault sin que te acuerdes")
- Augmentation ("cuando guardás algo crudo, lo organiza y enriquece")
- Triples / grafo tipado ("las notas se conectan entre sí")
- MCP server ("le preguntás al vault desde cualquier conversación con Claude")

## 10. Features opcionales — activar según vertical
- Concept promotion (útil: knowledge graph, facultad)
- Person resolver (útil: empleados, facultad)
- Embeddings semánticos (útil siempre que vault > ~50 notas)
- Outputs (digest, bio, year-review)

## 11. Big bang — presentación al user
Resumen en lenguaje user con secciones: 📒 vault, 🔌 fuentes, ⚡ processing,
💬 memory loop, 🔍 query, 🤖 MCP, 📬 outputs.
Pregunta de cierre: "¿Dale así, o algo no encaja?"
Si confirma → invocar materializer → dry-run → resultado.
"""


def build_system_prompt() -> str:
    """Compose the wizard's system prompt from static files + patterns directory."""
    language_rules = (_WIZARD_DIR / "language_rules.md").read_text()
    operative_rules = (_WIZARD_DIR / "operative_rules.md").read_text()
    checklist = (_WIZARD_DIR / "checklist.md").read_text()

    patterns_dir = _WIZARD_DIR / "patterns"
    patterns = [p.read_text() for p in sorted(patterns_dir.glob("*.md"))]

    tmpl = _ENV.from_string(_TEMPLATE)
    return tmpl.render(
        language_rules=language_rules,
        operative_rules=operative_rules,
        checklist=checklist,
        patterns=patterns,
    )
```

- [ ] **Step 6: Run tests** — Expected: 4 passed

- [ ] **Step 7: Commit**

```bash
git add src/rufino/wizard/ tests/test_wizard_assembler.py
git commit -m "feat(wizard): system prompt assembler with 11 sections + first pattern"
```

---

## Task 2: Add remaining 5 pattern files

**Files:**
- Create: `src/rufino/wizard/patterns/long_documents_extraction.md`
- Create: `src/rufino/wizard/patterns/person_centric_tracking.md`
- Create: `src/rufino/wizard/patterns/decision_log_with_rationale.md`
- Create: `src/rufino/wizard/patterns/temporal_self_observation.md`
- Create: `src/rufino/wizard/patterns/knowledge_graph_projects.md`

- [ ] **Step 1: Create all 5 pattern files**

`src/rufino/wizard/patterns/long_documents_extraction.md`:
```markdown
# Pattern: long_documents_extraction

## Trigger language
- "mis apuntes / lecturas / papers"
- "PDFs de"
- "leí esto y quiero recordarlo"
- "resumir mi research"

## Entity types típicos
- apunte, paper, doc, transcript

## Combinación de primitives
- Ingest con `output_mode: import_raw` (Drive / manual)
- Process con augmentación (extracción de temas, conexiones)
- Embeddings semánticos para búsqueda

## Casos
- Facultad
- Papers académicos
- Contratos
```

`src/rufino/wizard/patterns/person_centric_tracking.md`:
```markdown
# Pattern: person_centric_tracking

## Trigger language
- "personas / contactos / empleados / clientes"
- "1:1"
- "feedback sobre X"
- "qué hablé con Y"

## Entity types típicos
- persona, meeting, feedback, relation

## Combinación de primitives
- Memory loop con persona como entidad central
- Q&A loop para dedup de personas
- Output meeting-prep on_event

## Casos
- 1:1 con empleados
- CRM personal
- Profesores en vault de facultad
```

`src/rufino/wizard/patterns/decision_log_with_rationale.md`:
```markdown
# Pattern: decision_log_with_rationale

## Trigger language
- "decisiones"
- "por qué hicimos X"
- "registro de criterios"
- "ADRs"
- "no quiero olvidarme por qué"

## Entity types típicos
- decision, rationale, alternative

## Combinación de primitives
- Process con triple `supersedes` (decisión nueva reemplaza vieja)
- Lint orphans (decisiones sin contexto)
- Output search facetada

## Casos
- ADRs técnicos
- Decisiones de producto
- Jurisprudencia personal
```

`src/rufino/wizard/patterns/temporal_self_observation.md`:
```markdown
# Pattern: temporal_self_observation

## Trigger language
- "cómo viene mi semana / mes / año"
- "qué hice en"
- "patrones de mi"
- "evolución de"

## Entity types típicos
- (varias entidades agregadas en el tiempo)

## Combinación de primitives
- Múltiples Ingest con `output_mode: emit_fact`
- Output bio mensual + year-review + digest semanal

## Casos
- Tracking de hábitos
- Bio mensual
- Year-in-review
- Lo que Rufino actual hace para Val
```

`src/rufino/wizard/patterns/knowledge_graph_projects.md`:
```markdown
# Pattern: knowledge_graph_projects

## Trigger language
- "proyectos"
- "ideas conectadas"
- "vault tipo Obsidian"
- "knowledge graph"
- "todo mi conocimiento sobre"

## Entity types típicos
- proyecto, idea, concepto, persona

## Combinación de primitives
- Memory loop con proyecto-central
- Process con triples ricos
- Query grafo

## Casos
- Knowledge graph profesional
- Vault de research personal
- Documentación de proyectos en curso
```

- [ ] **Step 2: Update assembler test to verify all 6 patterns**

Modify `tests/test_wizard_assembler.py`:
```python
def test_includes_all_six_patterns():
    prompt = build_system_prompt()
    for pattern_name in [
        "discrete_events_with_metadata",
        "long_documents_extraction",
        "person_centric_tracking",
        "decision_log_with_rationale",
        "temporal_self_observation",
        "knowledge_graph_projects",
    ]:
        assert pattern_name in prompt, f"Pattern missing: {pattern_name}"
```

- [ ] **Step 3: Run tests** — Expected: 5 passed (including the new test)

- [ ] **Step 4: Commit**

```bash
git add src/rufino/wizard/patterns/ tests/test_wizard_assembler.py
git commit -m "feat(wizard): all 6 initial composition patterns"
```

---

## Task 3: WizardSpec schema

**Files:**
- Create: `src/rufino/wizard/spec_schema.py`
- Create: `tests/test_wizard_spec_schema.py`

- [ ] **Step 1: Failing test**

`tests/test_wizard_spec_schema.py`:
```python
import pytest
import json
from rufino.wizard.spec_schema import WizardSpec, validate_spec, SpecError


VALID_SPEC = {
    "vertical_name": "facultad",
    "patterns": ["long_documents_extraction", "person_centric_tracking"],
    "entities": ["apunte_clase", "materia", "profesor"],
    "sources": [
        {"adapter_name": "drive-pdfs", "output_mode": "import_raw"},
    ],
    "processing": [
        {"adapter_name": "apunte-clase", "note_type": "apunte_clase"},
    ],
    "outputs": [
        {"adapter_name": "digest-semanal", "cron": "0 18 * * 5"},
    ],
    "vocabulary": {
        "apunte_clase": "apuntes/<materia>/<YYYY-MM-DD>-<slug>.md",
        "materia": "materias/<slug>.md",
        "profesor": "profesores/<slug>.md",
    },
}


def test_validate_spec_accepts_valid():
    spec = validate_spec(VALID_SPEC)
    assert isinstance(spec, WizardSpec)
    assert spec.vertical_name == "facultad"
    assert len(spec.entities) == 3


def test_validate_spec_rejects_missing_field():
    bad = dict(VALID_SPEC)
    del bad["vertical_name"]
    with pytest.raises(SpecError, match="vertical_name"):
        validate_spec(bad)


def test_validate_spec_rejects_unknown_pattern():
    bad = dict(VALID_SPEC)
    bad["patterns"] = ["nonexistent_pattern"]
    with pytest.raises(SpecError, match="pattern"):
        validate_spec(bad)


def test_spec_can_load_from_json():
    spec_json = json.dumps(VALID_SPEC)
    spec = validate_spec(json.loads(spec_json))
    assert spec.vertical_name == "facultad"
```

- [ ] **Step 2: Run (fails)**

- [ ] **Step 3: Implement**

`src/rufino/wizard/spec_schema.py`:
```python
from dataclasses import dataclass
from typing import Any


class SpecError(Exception):
    """Raised when the wizard spec is invalid."""


KNOWN_PATTERNS = {
    "discrete_events_with_metadata",
    "long_documents_extraction",
    "person_centric_tracking",
    "decision_log_with_rationale",
    "temporal_self_observation",
    "knowledge_graph_projects",
}


@dataclass(frozen=True)
class WizardSpec:
    vertical_name: str
    patterns: tuple[str, ...]
    entities: tuple[str, ...]
    sources: tuple[dict, ...]
    processing: tuple[dict, ...]
    outputs: tuple[dict, ...]
    vocabulary: dict[str, str]


_REQUIRED = ("vertical_name", "patterns", "entities", "sources",
             "processing", "outputs", "vocabulary")


def validate_spec(raw: dict[str, Any]) -> WizardSpec:
    for f in _REQUIRED:
        if f not in raw:
            raise SpecError(f"Missing required field: {f}")

    unknown = set(raw["patterns"]) - KNOWN_PATTERNS
    if unknown:
        raise SpecError(f"Unknown pattern(s) in spec: {unknown}")

    return WizardSpec(
        vertical_name=raw["vertical_name"],
        patterns=tuple(raw["patterns"]),
        entities=tuple(raw["entities"]),
        sources=tuple(raw["sources"]),
        processing=tuple(raw["processing"]),
        outputs=tuple(raw["outputs"]),
        vocabulary=dict(raw["vocabulary"]),
    )
```

- [ ] **Step 4: Run tests** — Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/rufino/wizard/spec_schema.py tests/test_wizard_spec_schema.py
git commit -m "feat(wizard): WizardSpec schema + validator"
```

---

## Task 4: Materializer (big bang orchestrator)

**Files:**
- Create: `src/rufino/wizard/materializer.py`
- Create: `tests/test_wizard_materializer.py`

- [ ] **Step 1: Failing test**

`tests/test_wizard_materializer.py`:
```python
from pathlib import Path
from rufino.wizard.spec_schema import WizardSpec, validate_spec
from rufino.wizard.materializer import materialize, MaterializationResult


MINIMAL_SPEC = {
    "vertical_name": "facultad",
    "patterns": ["long_documents_extraction"],
    "entities": ["apunte_clase"],
    "sources": [],
    "processing": [],
    "outputs": [],
    "vocabulary": {"apunte_clase": "apuntes/<slug>.md"},
}


def test_materialize_creates_vault_skeleton(tmp_path: Path):
    vault = tmp_path / "vault"
    claude_home = tmp_path / ".claude"
    state_dir = tmp_path / ".rufino-state"

    spec = validate_spec(MINIMAL_SPEC)
    result = materialize(
        spec=spec,
        vault_root=vault,
        claude_home=claude_home,
        state_dir=state_dir,
    )

    assert isinstance(result, MaterializationResult)
    assert result.success
    assert vault.exists()
    assert (vault / "perfil.md").exists()
    assert (vault / "questions").exists()


def test_materialize_rollback_on_failure(tmp_path: Path):
    vault = tmp_path / "vault"
    claude_home = tmp_path / ".claude"
    state_dir = tmp_path / ".rufino-state"

    bad_spec = dict(MINIMAL_SPEC)
    bad_spec["vocabulary"] = {}  # entity without destination — will fail validation downstream
    spec = validate_spec(bad_spec)

    result = materialize(
        spec=spec,
        vault_root=vault,
        claude_home=claude_home,
        state_dir=state_dir,
    )
    # Even though spec is "valid" per schema, missing vocab for declared entity
    # is caught by materializer
    assert result.success is False or vault.exists() is False
```

- [ ] **Step 2: Run (fails)**

- [ ] **Step 3: Implement (skeleton; sources/processing/outputs deferred to integration)**

`src/rufino/wizard/materializer.py`:
```python
from dataclasses import dataclass, field
from pathlib import Path

from rufino.wizard.spec_schema import WizardSpec
from rufino.runtime.transaction_log import TransactionLog, apply_and_log


@dataclass
class MaterializationResult:
    success: bool
    vault_path: Path
    errors: list[str] = field(default_factory=list)


def materialize(
    *,
    spec: WizardSpec,
    vault_root: Path,
    claude_home: Path,
    state_dir: Path,
) -> MaterializationResult:
    """Big bang: create vault skeleton + install adapters transactionally.

    In v1, only the vault skeleton + perfil.md are created. Adapter installation
    delegated to the per-primitive installers from plans 2-7 is wired here as
    iteration completes. For now, the materializer produces a vault that the user
    can start populating.
    """
    state_dir.mkdir(parents=True, exist_ok=True)
    tx_log = TransactionLog(state_dir / f"materialize-{spec.vertical_name}.json")
    errors: list[str] = []

    # Pre-check: every entity has a vocabulary entry
    missing_vocab = [e for e in spec.entities if e not in spec.vocabulary]
    if missing_vocab:
        errors.append(f"Entities without vocabulary entry: {missing_vocab}")
        return MaterializationResult(success=False, vault_path=vault_root, errors=errors)

    try:
        apply_and_log(
            tx_log, op="mkdir", target=str(vault_root),
            apply_fn=lambda: vault_root.mkdir(parents=True),
            rollback="rmdir",
        )
        apply_and_log(
            tx_log, op="mkdir", target=str(vault_root / "questions"),
            apply_fn=lambda: (vault_root / "questions").mkdir(),
            rollback="rmdir",
        )
        # perfil.md initial seed
        perfil = vault_root / "perfil.md"
        apply_and_log(
            tx_log, op="write", target=str(perfil),
            apply_fn=lambda: perfil.write_text(
                f"---\ntags: [tipo/perfil, vertical/{spec.vertical_name}]\n---\n"
                f"# Perfil ({spec.vertical_name})\n\n(completá con tu info)\n"
            ),
            rollback="delete",
        )

        # Install Memory loop adapter for the vertical (uses installer from Plan 2)
        from rufino.engine.memory_loop.installer import install_memory_loop, InstallationError

        # If spec.vocabulary is provided, synthesize a minimal Memory loop manifest
        # in-memory and install it. Memory loop adapter dir is generated under
        # ~/.rufino/adapters/memory_loop/<vertical_name>/.
        adapter_dir = state_dir.parent / "adapters" / "memory_loop" / spec.vertical_name
        adapter_dir.mkdir(parents=True, exist_ok=True)
        destinations_yaml = "\n".join(
            f"  {entity}: \"{path}\"" for entity, path in spec.vocabulary.items()
        )
        manifest_text = (
            f"adapter_name: memory-loop-{spec.vertical_name}\n"
            f"vertical_name: {spec.vertical_name}\n"
            f"entity_types: {list(spec.entities)}\n"
            f"note_destinations:\n{destinations_yaml}\n"
            f"rule_extensions: []\n"
        )
        (adapter_dir / "manifest.yaml").write_text(manifest_text)
        try:
            install_memory_loop(
                adapter_dir=adapter_dir,
                claude_home=claude_home,
                vault_path=vault_root,
                log=tx_log,
            )
        except InstallationError as e:
            raise RuntimeError(f"Memory loop install failed: {e}") from e

        # NOTE: spec.sources / spec.processing / spec.outputs wiring requires
        # per-primitive installers (plans 4, 3, 5) which write adapter dirs +
        # plists/cron entries. This v1 materializer installs the Memory loop
        # only — that's enough for the user to start using Claude conversationally
        # with the vault. Worker adapter installation is invoked separately via
        # `rufino ingest`, `rufino process`, `rufino output` until the
        # corresponding installers are added to this orchestrator in a follow-up
        # iteration (tracked as a separate spec task — see Plan 8 Task 7+).

    except Exception as e:
        errors.append(f"Materialization failed: {e}; rolling back")
        tx_log.rollback()
        return MaterializationResult(success=False, vault_path=vault_root, errors=errors)

    return MaterializationResult(success=True, vault_path=vault_root, errors=errors)
```

- [ ] **Step 4: Run tests** — Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/rufino/wizard/materializer.py tests/test_wizard_materializer.py
git commit -m "feat(wizard): materializer big bang orchestrator (vault skeleton + tx log)"
```

---

## Task 5: CLI `rufino bootstrap` + `rufino materialize`

**Files:**
- Modify: `src/rufino/cli.py`
- Create: `tests/test_cli_wizard.py`

- [ ] **Step 1: Failing test**

`tests/test_cli_wizard.py`:
```python
import json
from pathlib import Path
from click.testing import CliRunner
from rufino.cli import cli


def test_materialize_cli_from_spec_file(tmp_path: Path):
    spec = {
        "vertical_name": "smoke",
        "patterns": ["long_documents_extraction"],
        "entities": ["doc"],
        "sources": [],
        "processing": [],
        "outputs": [],
        "vocabulary": {"doc": "docs/<slug>.md"},
    }
    spec_file = tmp_path / "spec.json"
    spec_file.write_text(json.dumps(spec))

    runner = CliRunner()
    result = runner.invoke(cli, [
        "materialize",
        "--spec", str(spec_file),
        "--vault", str(tmp_path / "vault"),
        "--claude-home", str(tmp_path / ".claude"),
        "--state-dir", str(tmp_path / ".rufino-state"),
    ])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "vault" / "perfil.md").exists()


def test_bootstrap_cli_prints_instructions(tmp_path: Path, monkeypatch):
    # bootstrap should print the system prompt to stdout OR exec claude;
    # tested here in --dry-run mode that just prints prompt.
    runner = CliRunner()
    result = runner.invoke(cli, [
        "bootstrap", "--dry-run",
    ])
    assert result.exit_code == 0
    assert "Rufino Framework Wizard" in result.output
```

- [ ] **Step 2: Run (fails)**

- [ ] **Step 3: Append to `src/rufino/cli.py`**

```python
import json
from rufino.wizard.system_prompt_assembler import build_system_prompt
from rufino.wizard.spec_schema import validate_spec
from rufino.wizard.materializer import materialize


@cli.command(name="bootstrap")
@click.option("--dry-run", is_flag=True, help="Print system prompt instead of running claude")
def bootstrap_cmd(dry_run: bool) -> None:
    """Start the conversational wizard."""
    system_prompt = build_system_prompt()
    if dry_run:
        click.echo(system_prompt)
        return
    # Real exec: spawn `claude -p` with system prompt
    import subprocess
    subprocess.run(
        ["claude", "-p", system_prompt, "--allowedTools",
         "Bash(rufino materialize:*),Bash(rufino query:*),Read,Write"],
        check=False,
    )


@cli.command(name="materialize")
@click.option("--spec", "spec_path", required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--vault", "vault_root", required=True, type=click.Path(path_type=Path))
@click.option("--claude-home", "claude_home", required=True, type=click.Path(path_type=Path))
@click.option("--state-dir", "state_dir", required=True, type=click.Path(path_type=Path))
def materialize_cmd(spec_path: Path, vault_root: Path, claude_home: Path, state_dir: Path) -> None:
    """Materialize the system described in a WizardSpec JSON file."""
    raw = json.loads(spec_path.read_text())
    try:
        spec = validate_spec(raw)
    except Exception as e:
        click.echo(f"Spec validation failed: {e}", err=True)
        raise click.exceptions.Exit(code=1)

    result = materialize(
        spec=spec,
        vault_root=vault_root,
        claude_home=claude_home,
        state_dir=state_dir,
    )

    if not result.success:
        for e in result.errors:
            click.echo(f"ERROR: {e}", err=True)
        raise click.exceptions.Exit(code=2)
    click.echo(f"Vault materialized at {result.vault_path}")
```

- [ ] **Step 4: Run tests** — Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/rufino/cli.py tests/test_cli_wizard.py
git commit -m "feat(wizard): CLI bootstrap (--dry-run) + materialize"
```

---

## Task 6: Auto-detect hook script

**Files:**
- Create: `src/rufino/wizard/auto_detect.sh`
- Create: `tests/test_wizard_auto_detect.py`

- [ ] **Step 1: Write the script**

`src/rufino/wizard/auto_detect.sh`:
```bash
#!/usr/bin/env bash
# Rufino Framework — auto-detect hook
# Detects empty vault + framework installed → suggests bootstrap.
# Installed by `rufino install-memory-loop` (plan 2) — but this hook is generic.

set -euo pipefail

VAULT="${RUFINO_VAULT:-}"
if [ -z "$VAULT" ] || [ ! -d "$VAULT" ]; then
    exit 0  # no vault configured → nothing to detect
fi

# "Empty" = no .md files except possibly perfil.md / preferencias.md
NOTE_COUNT=$(find "$VAULT" -name "*.md" 2>/dev/null | grep -vE "(perfil|preferencias)\.md$" | wc -l | tr -d ' ')

if [ "$NOTE_COUNT" = "0" ]; then
    echo "RUFINO HINT: Tu vault está vacío. Para armar tu sistema corré: rufino bootstrap"
fi
```

- [ ] **Step 2: Test the script**

`tests/test_wizard_auto_detect.py`:
```python
import os
import subprocess
from pathlib import Path


SCRIPT = Path(__file__).parent.parent / "src" / "rufino" / "wizard" / "auto_detect.sh"


def test_auto_detect_hints_on_empty_vault(tmp_vault: Path):
    env = os.environ.copy()
    env["RUFINO_VAULT"] = str(tmp_vault)
    completed = subprocess.run(
        ["bash", str(SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    assert "RUFINO HINT" in completed.stdout


def test_auto_detect_silent_on_populated_vault(tmp_vault: Path):
    (tmp_vault / "real-note.md").write_text("content")
    env = os.environ.copy()
    env["RUFINO_VAULT"] = str(tmp_vault)
    completed = subprocess.run(
        ["bash", str(SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    assert completed.stdout.strip() == ""


def test_auto_detect_ignores_perfil_md(tmp_vault: Path):
    (tmp_vault / "perfil.md").write_text("seed")
    env = os.environ.copy()
    env["RUFINO_VAULT"] = str(tmp_vault)
    completed = subprocess.run(
        ["bash", str(SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
    )
    assert "RUFINO HINT" in completed.stdout  # perfil-only still counts as empty
```

- [ ] **Step 3: Make script executable**

Run: `chmod +x src/rufino/wizard/auto_detect.sh`

- [ ] **Step 4: Run tests** — Expected: 3 passed

- [ ] **Step 5: Run full suite**

Run: `pytest -v` — all pass

- [ ] **Step 6: Commit**

```bash
git add src/rufino/wizard/auto_detect.sh tests/test_wizard_auto_detect.py
git commit -m "feat(wizard): auto-detect hook for empty vault"
```

---

---

## Task 7: Prereqs check (spec 6.10)

**Files:**
- Create: `src/rufino/runtime/prereq_checker.py`
- Create: `tests/test_runtime_prereq_checker.py`

- [ ] **Step 1: Failing test**

`tests/test_runtime_prereq_checker.py`:
```python
import pytest
from unittest.mock import patch
from rufino.runtime.prereq_checker import (
    PrereqCheck,
    check_prereq,
    BUILT_IN_CHECKS,
)


def test_ollama_check_passes_when_command_exists():
    with patch("shutil.which", return_value="/opt/homebrew/bin/ollama"):
        result = check_prereq(PrereqCheck(
            name="ollama",
            kind="command",
            target="ollama",
            for_feature="embeddings",
        ))
        assert result.ok


def test_ollama_check_fails_when_missing():
    with patch("shutil.which", return_value=None):
        result = check_prereq(PrereqCheck(
            name="ollama",
            kind="command",
            target="ollama",
            for_feature="embeddings",
        ))
        assert not result.ok
        assert "embeddings" in result.message


def test_python_version_check():
    result = check_prereq(PrereqCheck(
        name="python311",
        kind="python_min_version",
        target="3.11",
        for_feature="transform_hooks",
    ))
    # Test runner runs on >=3.11 per pyproject.toml
    assert result.ok


def test_built_in_checks_present():
    names = {c.name for c in BUILT_IN_CHECKS}
    assert "ollama" in names
    assert "security_cli" in names
    assert "python311" in names
```

- [ ] **Step 2: Run (fails)**

- [ ] **Step 3: Implement**

`src/rufino/runtime/prereq_checker.py`:
```python
import shutil
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class PrereqCheck:
    name: str
    kind: str          # "command" | "python_min_version" | "file_exists"
    target: str        # command name, version string, or path
    for_feature: str   # human-readable feature label for messages


@dataclass(frozen=True)
class CheckResult:
    ok: bool
    message: str


def check_prereq(check: PrereqCheck) -> CheckResult:
    if check.kind == "command":
        path = shutil.which(check.target)
        if path:
            return CheckResult(ok=True, message=f"{check.target} found at {path}")
        return CheckResult(
            ok=False,
            message=f"{check.target!r} not installed — required for {check.for_feature}",
        )

    if check.kind == "python_min_version":
        major, minor = (int(x) for x in check.target.split("."))
        if sys.version_info >= (major, minor):
            return CheckResult(ok=True, message=f"python {sys.version_info[:2]}")
        return CheckResult(
            ok=False,
            message=f"python {check.target}+ required for {check.for_feature}",
        )

    raise ValueError(f"Unknown check kind: {check.kind!r}")


BUILT_IN_CHECKS = [
    PrereqCheck(name="ollama", kind="command", target="ollama",
                for_feature="embeddings"),
    PrereqCheck(name="security_cli", kind="command", target="security",
                for_feature="Keychain secrets (macOS)"),
    PrereqCheck(name="node", kind="command", target="node",
                for_feature="WhatsApp ingestor"),
    PrereqCheck(name="python311", kind="python_min_version", target="3.11",
                for_feature="transform hooks"),
    PrereqCheck(name="gh_cli", kind="command", target="gh",
                for_feature="GitHub ingestor"),
    PrereqCheck(name="ripgrep", kind="command", target="rg",
                for_feature="lexical search performance"),
]
```

- [ ] **Step 4: Run tests** — Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/rufino/runtime/prereq_checker.py tests/test_runtime_prereq_checker.py
git commit -m "feat(wizard): prereq_checker with catalog of built-in checks"
```

---

## Task 8: Auto-generated post-bootstrap README in user's vault (spec 6.11)

**Files:**
- Create: `src/rufino/wizard/post_bootstrap_docs.py`
- Modify: `src/rufino/wizard/materializer.py`
- Create: `tests/test_wizard_post_bootstrap_docs.py`

- [ ] **Step 1: Failing test**

`tests/test_wizard_post_bootstrap_docs.py`:
```python
from pathlib import Path
from rufino.wizard.spec_schema import WizardSpec, validate_spec
from rufino.wizard.post_bootstrap_docs import render_user_readme


SPEC = {
    "vertical_name": "facultad",
    "patterns": ["long_documents_extraction"],
    "entities": ["apunte_clase", "materia"],
    "sources": [{"adapter_name": "drive-pdfs", "output_mode": "import_raw"}],
    "processing": [{"adapter_name": "apunte-clase", "note_type": "apunte_clase"}],
    "outputs": [{"adapter_name": "digest-semanal", "cron": "0 18 * * 5"}],
    "vocabulary": {
        "apunte_clase": "apuntes/<materia>/<YYYY-MM-DD>-<slug>.md",
        "materia": "materias/<slug>.md",
    },
}


def test_readme_in_user_language():
    spec = validate_spec(SPEC)
    readme = render_user_readme(spec)
    # User-facing language — no technical jargon
    assert "manifest" not in readme.lower()
    assert "adapter" not in readme.lower()
    # Has expected sections
    assert "Qué tenés acá" in readme
    assert "Cómo agregar cosas" in readme
    assert "Cómo encontrar cosas" in readme
    # Lists the user's entities
    assert "apunte_clase" in readme or "Apuntes de clase" in readme.lower() or "apunte" in readme.lower()


def test_readme_mentions_vertical_name():
    spec = validate_spec(SPEC)
    readme = render_user_readme(spec)
    assert "facultad" in readme
```

- [ ] **Step 2: Run (fails)**

- [ ] **Step 3: Implement**

`src/rufino/wizard/post_bootstrap_docs.py`:
```python
from rufino.wizard.spec_schema import WizardSpec


def render_user_readme(spec: WizardSpec) -> str:
    """Render a user-facing README for the freshly-materialized vault.

    Uses the language rules of the wizard: NO technical jargon.
    """
    entities_list = "\n".join(f"- {e.replace('_', ' ')}" for e in spec.entities)
    has_outputs = len(spec.outputs) > 0

    return f"""# Tu vault Rufino (vertical: {spec.vertical_name})

## Qué tenés acá

Tu vault organiza:

{entities_list}

Cada cosa se guarda automáticamente en la carpeta correcta, sin que tengas
que pensarlo. Las notas relacionadas se conectan entre sí, y los temas que
aparecen seguido se vuelven páginas dedicadas con el tiempo.

## Cómo agregar cosas

Tres caminos:

1. **Tirá archivos al inbox** — cualquier cosa que dejes en `inbox/`
   (PDF, markdown, texto) se organiza automáticamente.
2. **Conversá con Claude Code** — mientras hablás, Claude guarda lo
   valioso al vault sin que te tengas que acordar. Al cerrar la sesión
   te pregunta si hay algo más.
3. **Escribí a mano** — abrí tu editor en el vault y escribí donde quieras.
   Lo organiza después.

## Cómo encontrar cosas

- **Lenguaje natural**: preguntale a Claude algo como
  *"qué tengo sobre X"* y te contesta.
- **Búsqueda directa**: `rufino query "tu pregunta" --vault {spec.vertical_name}`
- **Navegando conexiones**: abrí cualquier nota y seguí los wikilinks.

## Desde otras conversaciones con Claude Code

Incluso fuera del vault, podés preguntarle a Claude sobre tu información.
El servicio MCP `ask-rufino` queda registrado y disponible en cualquier
sesión de Claude Code.

{"## Vas a recibir" if has_outputs else ""}
{_render_outputs_section(spec) if has_outputs else ""}

## Si algo no funciona

- Logs en `~/.rufino/state/`
- Si el sistema no responde como esperás, revisá `~/.rufino/state/`.
- Para parar todo: detené los crons (los nombres empiezan con `rufino.`).

## Si querés cambiar el sistema

Corré `rufino bootstrap` de nuevo. Te guía para agregar entidades, fuentes
o resúmenes nuevos.
"""


def _render_outputs_section(spec: WizardSpec) -> str:
    items = []
    for out in spec.outputs:
        name = out.get("adapter_name", "output")
        cron = out.get("cron", "")
        items.append(f"- **{name.replace('-', ' ')}**" + (f" ({cron})" if cron else ""))
    return "\n".join(items)
```

- [ ] **Step 4: Wire into materializer**

Modify `src/rufino/wizard/materializer.py` — at the end of the `try:` block in `materialize()`, before the `except`:

```python
        # Write user-facing README into the vault
        from rufino.wizard.post_bootstrap_docs import render_user_readme
        readme = vault_root / "README.md"
        apply_and_log(
            tx_log, op="write", target=str(readme),
            apply_fn=lambda: readme.write_text(render_user_readme(spec)),
            rollback="delete",
        )
```

- [ ] **Step 5: Run tests** — Expected: 2 passed + existing materializer tests still pass

Run: `pytest tests/test_wizard_*.py -v`

- [ ] **Step 6: Commit**

```bash
git add src/rufino/wizard/post_bootstrap_docs.py src/rufino/wizard/materializer.py tests/test_wizard_post_bootstrap_docs.py
git commit -m "feat(wizard): auto-generated user-facing README post-bootstrap (spec 6.11)"
```

---

## Self-review checklist

- [ ] System prompt contains all 11 sections + 6 patterns
- [ ] No unfilled jinja placeholders escape `build_system_prompt`
- [ ] WizardSpec rejects unknown pattern names
- [ ] Materializer rolls back on any failure
- [ ] CLI `rufino bootstrap --dry-run` prints the full prompt
- [ ] CLI `rufino materialize` exits non-zero on spec validation failure
- [ ] Auto-detect script silent on populated vault, hints on empty

## Done criteria

- `pytest tests/test_wizard_*.py -v` all pass
- `./cli/rufino bootstrap --dry-run | head -20` shows the wizard's identity section
- `./cli/rufino materialize --spec <file> --vault X --claude-home Y --state-dir Z` creates `vault/perfil.md`
- Auto-detect hook prints HINT only when vault has no real notes
