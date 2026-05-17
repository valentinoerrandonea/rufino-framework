# Plan 3 — Process pipeline primitive Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementar la primitive Process: el shape "worker adapter" (carpeta + manifest + prompt + transform.py opcional), el dispatcher con modos `full|light|lint`, helpers comunes (frontmatter validator, triple extractor, indices updater, concept promotion, person registration), context injectors, e integración con Q&A loop y Query layer (vía stubs durante este plan). Al final, una nota cruda en el inbox se puede procesar end-to-end con un adapter `process-apunte-clase` de ejemplo.

**Architecture:** El dispatcher es un loop fijo de 10 pasos. Adapter declara comportamiento via manifest + prompt. LLM call es la abstracción `LLMClient` (con backend stub en este plan; backend real Anthropic en plan posterior). Q&A loop y Query layer se importan como módulos pero usan stubs in-memory aquí.

**Tech Stack:** Python 3.11+, pyyaml, jinja2 (templating de prompts), pytest. Para PDF extraction: `pypdf`.

**Dependencias previas:** Plan 1 (Foundation), Plan 2 (Memory loop — no usado directamente pero comparte fixtures de vault).

**Plans que dependen de este:** Plan 4 (Ingest — invoca Process inmediato cuando `import_raw`), Plan 8 (Wizard — genera adapters de Process).

---

## File Structure

```
src/rufino/engine/process/
├── __init__.py
├── manifest.py             # WorkerAdapterManifest + parser
├── validator.py            # WorkerAdapterValidator
├── dispatcher.py           # process(note_path, mode) entry
├── llm_client.py           # LLMClient interface + StubLLMClient
├── pdf_extract.py          # extract_text_from_pdf wrapper
├── helpers/
│   ├── __init__.py
│   ├── frontmatter.py      # parse_frontmatter, render_frontmatter, validate_schema
│   ├── triples.py          # extract_triples, validate_against_vocab
│   ├── indices.py          # update_index_files
│   ├── concepts.py         # promote_concepts (≥N occurrences)
│   └── persons.py          # register_persons
├── context_injectors.py    # apply_context_injectors (calls Query layer stub)
└── qa_integration.py       # ask_user wrapper (calls Q&A loop stub)
src/rufino/cli.py           # MODIFY: add `rufino process <note_path>`
tests/test_process_*.py     # one test file per module
tests/fixtures/adapters/process-apunte-clase/
├── manifest.yaml
└── prompt.md
tests/fixtures/notes/
├── crude_apunte.md
└── crude_apunte_with_triples.md
```

---

## Task 1: Worker adapter manifest + parser

**Files:**
- Create: `src/rufino/engine/process/__init__.py`
- Create: `src/rufino/engine/process/manifest.py`
- Create: `tests/test_process_manifest.py`

- [ ] **Step 1: Write the failing test**

`tests/test_process_manifest.py`:
```python
import pytest
from rufino.engine.process.manifest import (
    WorkerAdapterManifest,
    parse_worker_manifest,
    ManifestParseError,
)


VALID = """
adapter_name: apunte-clase
note_type: apunte_clase
applies_when:
  source_dir: rufino/inbox/
  matches_pattern: ["*.pdf", "*.md", "*.txt"]
llm: sonnet
mode_default: full
output_schema:
  required:
    materia: { type: enum_dynamic, source: "tags: materia/" }
    fecha_clase: date
    topics: list[str]
  optional:
    profesor: persona_ref
triple_vocabulary: [tema-de, expuesto-por, extiende]
tag_axes:
  - { axis: materia, format: "materia/<slug>", required: true }
  - { axis: tema, format: "tema/<slug>", min: 1 }
destination_path: "apuntes/{materia}/{fecha_clase}-{slug}.md"
qa_triggers:
  - { name: materia_ambigua, condition: "match_count(materia) >= 2" }
context_injectors:
  - { name: apuntes_previos, query: "tag=materia/<materia>, last 10 by date" }
"""


def test_parses_full_worker_manifest():
    m = parse_worker_manifest(VALID)
    assert m.adapter_name == "apunte-clase"
    assert m.note_type == "apunte_clase"
    assert m.llm == "sonnet"
    assert m.mode_default == "full"
    assert "tema-de" in m.triple_vocabulary
    assert m.destination_path == "apuntes/{materia}/{fecha_clase}-{slug}.md"
    assert m.qa_triggers[0]["name"] == "materia_ambigua"


def test_missing_required_fields_raise():
    with pytest.raises(ManifestParseError, match="adapter_name"):
        parse_worker_manifest("note_type: x\n")


def test_invalid_mode_default_raises():
    yaml = VALID.replace("mode_default: full", "mode_default: bogus")
    with pytest.raises(ManifestParseError, match="mode_default"):
        parse_worker_manifest(yaml)


def test_destination_must_be_relative():
    yaml = VALID.replace(
        'destination_path: "apuntes/{materia}/{fecha_clase}-{slug}.md"',
        'destination_path: "/abs/path.md"',
    )
    with pytest.raises(ManifestParseError, match="absolute"):
        parse_worker_manifest(yaml)
```

- [ ] **Step 2: Run test (fails)**

Run: `pytest tests/test_process_manifest.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write manifest module**

`src/rufino/engine/process/__init__.py`: `` (empty)

`src/rufino/engine/process/manifest.py`:
```python
from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Any
import yaml


class ManifestParseError(Exception):
    """Raised when worker adapter manifest is invalid."""


VALID_MODES = {"full", "light", "lint"}


@dataclass(frozen=True)
class WorkerAdapterManifest:
    adapter_name: str
    note_type: str
    applies_when: dict[str, Any]
    llm: str
    mode_default: str
    output_schema: dict[str, Any]
    triple_vocabulary: tuple[str, ...]
    tag_axes: tuple[dict[str, Any], ...]
    destination_path: str
    qa_triggers: tuple[dict[str, Any], ...]
    context_injectors: tuple[dict[str, Any], ...]
    transform_hook: str | None = None


_REQUIRED = ("adapter_name", "note_type", "applies_when", "llm", "mode_default",
             "output_schema", "triple_vocabulary", "tag_axes", "destination_path")


def parse_worker_manifest(yaml_text: str) -> WorkerAdapterManifest:
    try:
        raw = yaml.safe_load(yaml_text)
    except yaml.YAMLError as e:
        raise ManifestParseError(f"Invalid YAML: {e}") from e

    if not isinstance(raw, dict):
        raise ManifestParseError("Manifest root must be a mapping")

    missing = [f for f in _REQUIRED if f not in raw]
    if missing:
        raise ManifestParseError(f"Missing required fields: {missing}")

    if raw["mode_default"] not in VALID_MODES:
        raise ManifestParseError(
            f"mode_default must be one of {VALID_MODES}, got {raw['mode_default']!r}"
        )

    if PurePath(raw["destination_path"]).is_absolute():
        raise ManifestParseError(
            f"destination_path must be relative, got absolute {raw['destination_path']!r}"
        )

    return WorkerAdapterManifest(
        adapter_name=raw["adapter_name"],
        note_type=raw["note_type"],
        applies_when=raw["applies_when"],
        llm=raw["llm"],
        mode_default=raw["mode_default"],
        output_schema=raw["output_schema"],
        triple_vocabulary=tuple(raw["triple_vocabulary"]),
        tag_axes=tuple(raw["tag_axes"]),
        destination_path=raw["destination_path"],
        qa_triggers=tuple(raw.get("qa_triggers", [])),
        context_injectors=tuple(raw.get("context_injectors", [])),
        transform_hook=raw.get("transform_hook"),
    )
```

- [ ] **Step 4: Run tests** — Expected: 4 passed

Run: `pytest tests/test_process_manifest.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/rufino/engine/process/__init__.py src/rufino/engine/process/manifest.py tests/test_process_manifest.py
git commit -m "feat(process): worker adapter manifest parser"
```

---

## Task 2: Frontmatter helpers

**Files:**
- Create: `src/rufino/engine/process/helpers/__init__.py`
- Create: `src/rufino/engine/process/helpers/frontmatter.py`
- Create: `tests/test_process_helpers_frontmatter.py`

- [ ] **Step 1: Failing test**

`tests/test_process_helpers_frontmatter.py`:
```python
import pytest
from rufino.engine.process.helpers.frontmatter import (
    parse_frontmatter,
    render_frontmatter,
    validate_against_schema,
    FrontmatterError,
)


def test_parse_roundtrip():
    note = "---\ntitle: hello\ntags: [a, b]\n---\nBody here.\n"
    fm, body = parse_frontmatter(note)
    assert fm == {"title": "hello", "tags": ["a", "b"]}
    assert body == "Body here.\n"


def test_parse_note_without_frontmatter():
    fm, body = parse_frontmatter("Just body.\n")
    assert fm == {}
    assert body == "Just body.\n"


def test_render_frontmatter():
    rendered = render_frontmatter({"a": 1, "tags": ["x"]}, "Body.\n")
    assert rendered.startswith("---\n")
    assert "a: 1" in rendered
    assert rendered.endswith("Body.\n")


def test_validate_schema_required_present():
    schema = {"required": {"materia": {"type": "string"}, "topics": "list[str]"}}
    fm = {"materia": "ml-i", "topics": ["a"]}
    validate_against_schema(fm, schema)  # no raise


def test_validate_schema_required_missing_raises():
    schema = {"required": {"materia": {"type": "string"}}}
    fm = {"other": "x"}
    with pytest.raises(FrontmatterError, match="materia"):
        validate_against_schema(fm, schema)


def test_validate_schema_optional_absent_ok():
    schema = {"required": {}, "optional": {"profesor": "persona_ref"}}
    validate_against_schema({}, schema)  # no raise
```

- [ ] **Step 2: Run (fails)**

Run: `pytest tests/test_process_helpers_frontmatter.py -v`

- [ ] **Step 3: Implement**

`src/rufino/engine/process/helpers/__init__.py`: `` (empty)

`src/rufino/engine/process/helpers/frontmatter.py`:
```python
from typing import Any
import yaml


class FrontmatterError(Exception):
    """Raised when frontmatter parsing or validation fails."""


def parse_frontmatter(note_text: str) -> tuple[dict[str, Any], str]:
    """Return (frontmatter_dict, body). Empty dict if no frontmatter present."""
    if not note_text.startswith("---\n"):
        return {}, note_text

    try:
        _, fm_block, body = note_text.split("---\n", 2)
    except ValueError:
        raise FrontmatterError("Frontmatter delimiter unterminated")

    try:
        fm = yaml.safe_load(fm_block) or {}
    except yaml.YAMLError as e:
        raise FrontmatterError(f"Invalid YAML in frontmatter: {e}") from e

    if not isinstance(fm, dict):
        raise FrontmatterError("Frontmatter must be a mapping")

    return fm, body


def render_frontmatter(fm: dict[str, Any], body: str) -> str:
    """Render frontmatter + body to a markdown note string."""
    fm_yaml = yaml.safe_dump(fm, default_flow_style=False, sort_keys=True)
    return f"---\n{fm_yaml}---\n{body}"


def validate_against_schema(fm: dict[str, Any], schema: dict[str, Any]) -> None:
    """Validate frontmatter against output_schema declared in adapter manifest.

    Required fields must be present. Optional fields are not checked for presence.
    Type-level validation (date, list[str], etc.) is best-effort in v1.
    """
    required = schema.get("required", {})
    for field_name in required:
        if field_name not in fm:
            raise FrontmatterError(f"Required field missing: {field_name}")
```

- [ ] **Step 4: Run tests** — Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/rufino/engine/process/helpers/ tests/test_process_helpers_frontmatter.py
git commit -m "feat(process): frontmatter parse + render + schema validation"
```

---

## Task 3: Triple helpers

**Files:**
- Create: `src/rufino/engine/process/helpers/triples.py`
- Create: `tests/test_process_helpers_triples.py`

- [ ] **Step 1: Failing test**

`tests/test_process_helpers_triples.py`:
```python
import pytest
from rufino.engine.process.helpers.triples import (
    extract_triples,
    validate_triples_against_vocab,
    TripleError,
)


def test_extract_triples_from_frontmatter():
    fm = {
        "triples": [
            {"r": "tema-de", "o": "ml-i"},
            {"r": "expuesto-por", "o": "mendez"},
        ]
    }
    triples = extract_triples(fm)
    assert triples == [("tema-de", "ml-i"), ("expuesto-por", "mendez")]


def test_no_triples_returns_empty():
    assert extract_triples({}) == []


def test_validate_triples_passes_for_known_relations():
    vocab = {"tema-de", "expuesto-por", "extiende"}
    validate_triples_against_vocab(
        [("tema-de", "x"), ("extiende", "y")],
        vocab,
    )


def test_validate_triples_rejects_unknown_relation():
    vocab = {"tema-de"}
    with pytest.raises(TripleError, match="invented"):
        validate_triples_against_vocab([("invented", "x")], vocab)
```

- [ ] **Step 2: Run (fails)**

- [ ] **Step 3: Implement**

`src/rufino/engine/process/helpers/triples.py`:
```python
from typing import Any


class TripleError(Exception):
    """Raised when triples are malformed or violate vocabulary."""


def extract_triples(frontmatter: dict[str, Any]) -> list[tuple[str, str]]:
    """Extract (relation, object) pairs from the `triples:` block of frontmatter.

    Frontmatter format: triples: [{r: <relation>, o: <object>}, ...]
    """
    raw = frontmatter.get("triples", [])
    if not isinstance(raw, list):
        raise TripleError("triples must be a list")

    out: list[tuple[str, str]] = []
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict) or "r" not in entry or "o" not in entry:
            raise TripleError(f"triples[{i}] missing 'r' or 'o': {entry!r}")
        out.append((entry["r"], entry["o"]))
    return out


def validate_triples_against_vocab(
    triples: list[tuple[str, str]],
    vocab: set[str],
) -> None:
    """Ensure every relation in `triples` is declared in `vocab`."""
    for r, _ in triples:
        if r not in vocab:
            raise TripleError(f"Unknown/invented relation {r!r}; vocab={sorted(vocab)}")
```

- [ ] **Step 4: Run tests** — Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/rufino/engine/process/helpers/triples.py tests/test_process_helpers_triples.py
git commit -m "feat(process): triple extraction + vocabulary validation"
```

---

## Task 4: Index updater + concept promotion + persons

**Files:**
- Create: `src/rufino/engine/process/helpers/indices.py`
- Create: `src/rufino/engine/process/helpers/concepts.py`
- Create: `src/rufino/engine/process/helpers/persons.py`
- Create: `tests/test_process_helpers_indices.py`

- [ ] **Step 1: Failing test**

`tests/test_process_helpers_indices.py`:
```python
from pathlib import Path
from rufino.engine.process.helpers.indices import update_tag_index, append_to_log
from rufino.engine.process.helpers.concepts import promote_concepts
from rufino.engine.process.helpers.persons import register_persons


def test_tag_index_appends_note(tmp_vault: Path):
    tag_index = tmp_vault / "_meta" / "_tags.md"
    tag_index.parent.mkdir()
    tag_index.write_text("# Tags\n")

    update_tag_index(tag_index, tag="materia/ml-i", note_slug="2026-05-16-clase")

    content = tag_index.read_text()
    assert "materia/ml-i" in content
    assert "2026-05-16-clase" in content


def test_log_appends(tmp_vault: Path):
    log = tmp_vault / "_meta" / "_processing-log.md"
    log.parent.mkdir()
    log.write_text("# Log\n")

    append_to_log(log, message="processed clase3")
    content = log.read_text()
    assert "processed clase3" in content


def test_concept_promotion_threshold(tmp_vault: Path):
    conceptos_dir = tmp_vault / "conceptos"
    conceptos_dir.mkdir()

    # Concept "regresion-logistica" appears in 2 notes → promoted
    promoted = promote_concepts(
        conceptos_dir,
        mentions={"regresion-logistica": 2, "isolated-concept": 1},
        threshold=2,
    )
    assert "regresion-logistica" in promoted
    assert "isolated-concept" not in promoted
    assert (conceptos_dir / "regresion-logistica.md").exists()


def test_register_persons_creates_files(tmp_vault: Path):
    people_dir = tmp_vault / "personas"
    people_dir.mkdir()

    created = register_persons(people_dir, persons=["mendez", "garcia"])
    assert "mendez" in created
    assert (people_dir / "mendez.md").exists()
    assert (people_dir / "garcia.md").exists()


def test_register_persons_idempotent(tmp_vault: Path):
    people_dir = tmp_vault / "personas"
    people_dir.mkdir()
    (people_dir / "mendez.md").write_text("# Mendez\n(existing)\n")

    created = register_persons(people_dir, persons=["mendez"])
    assert created == []  # already existed
    assert (people_dir / "mendez.md").read_text() == "# Mendez\n(existing)\n"
```

- [ ] **Step 2: Run (fails)**

- [ ] **Step 3: Implement**

`src/rufino/engine/process/helpers/indices.py`:
```python
from datetime import datetime
from pathlib import Path


def update_tag_index(tag_index: Path, *, tag: str, note_slug: str) -> None:
    """Append a (tag, note) line to the tag index. Idempotent for (tag,note) pairs."""
    line = f"- `{tag}` → [[{note_slug}]]\n"
    existing = tag_index.read_text() if tag_index.exists() else "# Tags\n"
    if line in existing:
        return
    tag_index.write_text(existing + line)


def append_to_log(log: Path, *, message: str) -> None:
    """Append a timestamped line to the processing log."""
    ts = datetime.utcnow().isoformat(timespec="seconds")
    existing = log.read_text() if log.exists() else "# Processing log\n"
    log.write_text(existing + f"- {ts}Z — {message}\n")
```

`src/rufino/engine/process/helpers/concepts.py`:
```python
from pathlib import Path


def promote_concepts(
    conceptos_dir: Path,
    *,
    mentions: dict[str, int],
    threshold: int,
) -> list[str]:
    """For each concept slug with mentions >= threshold, create a stub note if absent.

    Returns list of newly promoted concept slugs.
    """
    promoted: list[str] = []
    for slug, count in mentions.items():
        if count < threshold:
            continue
        target = conceptos_dir / f"{slug}.md"
        if target.exists():
            continue
        target.write_text(
            f"---\ntags: [tipo/concepto, concepto/{slug}]\n---\n"
            f"# {slug}\n\nConcepto promovido automáticamente ({count} menciones).\n"
        )
        promoted.append(slug)
    return promoted
```

`src/rufino/engine/process/helpers/persons.py`:
```python
from pathlib import Path


def register_persons(people_dir: Path, *, persons: list[str]) -> list[str]:
    """For each person slug not yet in `people_dir`, create a stub note.

    Returns list of newly created slugs.
    """
    created: list[str] = []
    for slug in persons:
        target = people_dir / f"{slug}.md"
        if target.exists():
            continue
        target.write_text(
            f"---\ntags: [tipo/persona, persona/{slug}]\n---\n"
            f"# {slug}\n\n(stub — completar con contexto)\n"
        )
        created.append(slug)
    return created
```

- [ ] **Step 4: Run tests** — Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/rufino/engine/process/helpers/indices.py src/rufino/engine/process/helpers/concepts.py src/rufino/engine/process/helpers/persons.py tests/test_process_helpers_indices.py
git commit -m "feat(process): indices/concepts/persons helpers"
```

---

## Task 5: LLM client interface + stub

**Files:**
- Create: `src/rufino/engine/process/llm_client.py`
- Create: `tests/test_process_llm_client.py`

- [ ] **Step 1: Failing test**

`tests/test_process_llm_client.py`:
```python
from rufino.engine.process.llm_client import (
    LLMClient,
    StubLLMClient,
    LLMResponse,
)


def test_stub_returns_canned_response():
    stub = StubLLMClient(canned_response="---\ntitle: stub\n---\nBody from stub.\n")
    resp = stub.complete(prompt="ignored", model="sonnet")
    assert isinstance(resp, LLMResponse)
    assert "stub" in resp.text


def test_stub_protocol_compliance():
    stub = StubLLMClient(canned_response="x")
    assert isinstance(stub, LLMClient)


def test_stub_records_calls():
    stub = StubLLMClient(canned_response="r")
    stub.complete(prompt="hello", model="sonnet")
    stub.complete(prompt="world", model="opus")
    assert len(stub.calls) == 2
    assert stub.calls[0] == ("hello", "sonnet")
```

- [ ] **Step 2: Run (fails)**

- [ ] **Step 3: Implement**

`src/rufino/engine/process/llm_client.py`:
```python
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class LLMResponse:
    text: str
    # Future: tokens_used, model_used, finish_reason


class LLMClient(Protocol):
    def complete(self, *, prompt: str, model: str) -> LLMResponse: ...


@dataclass
class StubLLMClient:
    """Stub for tests. Returns a pre-canned response and records every call."""
    canned_response: str
    calls: list[tuple[str, str]] = field(default_factory=list)

    def complete(self, *, prompt: str, model: str) -> LLMResponse:
        self.calls.append((prompt, model))
        return LLMResponse(text=self.canned_response)
```

- [ ] **Step 4: Run tests** — Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/rufino/engine/process/llm_client.py tests/test_process_llm_client.py
git commit -m "feat(process): LLMClient interface + StubLLMClient for tests"
```

---

## Task 6: Stubs for Query layer + Q&A loop (used by dispatcher)

**Files:**
- Create: `src/rufino/engine/process/context_injectors.py`
- Create: `src/rufino/engine/process/qa_integration.py`
- Create: `tests/test_process_context_injectors.py`

- [ ] **Step 1: Failing test**

`tests/test_process_context_injectors.py`:
```python
from rufino.engine.process.context_injectors import (
    apply_context_injectors,
    StubQueryLayer,
)


def test_injector_renders_query_into_context():
    query_stub = StubQueryLayer(canned_results={
        "tag=materia/ml-i, last 10 by date": ["clase1.md", "clase2.md"],
    })
    injectors = [
        {"name": "apuntes_previos", "query": "tag=materia/<materia>, last 10 by date"},
    ]
    context = apply_context_injectors(
        injectors=injectors,
        variables={"materia": "ml-i"},
        query=query_stub,
    )
    assert "apuntes_previos" in context
    assert "clase1.md" in context["apuntes_previos"]
    assert "clase2.md" in context["apuntes_previos"]


def test_injector_skips_when_variable_missing():
    query_stub = StubQueryLayer(canned_results={})
    injectors = [
        {"name": "x", "query": "tag=<missing_var>"},
    ]
    context = apply_context_injectors(
        injectors=injectors,
        variables={},
        query=query_stub,
    )
    assert context["x"] == "(unable to resolve query — missing variables)"
```

- [ ] **Step 2: Run (fails)**

- [ ] **Step 3: Implement**

`src/rufino/engine/process/context_injectors.py`:
```python
import re
from dataclasses import dataclass, field
from typing import Protocol


class QueryLayer(Protocol):
    def run(self, query_string: str) -> list[str]: ...


@dataclass
class StubQueryLayer:
    canned_results: dict[str, list[str]] = field(default_factory=dict)

    def run(self, query_string: str) -> list[str]:
        return self.canned_results.get(query_string, [])


_VAR_RE = re.compile(r"<(\w+)>")


def apply_context_injectors(
    *,
    injectors: list[dict],
    variables: dict[str, str],
    query: QueryLayer,
) -> dict[str, str]:
    """Render each injector's query with `variables`, run via Query layer, collect results.

    If a variable in the query is missing from `variables`, the injector returns a
    placeholder string instead of failing — this lets the LLM proceed with partial context.
    """
    context: dict[str, str] = {}
    for inj in injectors:
        name = inj["name"]
        template = inj["query"]
        missing = [m.group(1) for m in _VAR_RE.finditer(template) if m.group(1) not in variables]
        if missing:
            context[name] = "(unable to resolve query — missing variables)"
            continue
        rendered = _VAR_RE.sub(lambda m: variables[m.group(1)], template)
        results = query.run(rendered)
        context[name] = "\n".join(f"- {r}" for r in results) if results else "(no results)"
    return context
```

`src/rufino/engine/process/qa_integration.py`:
```python
from dataclasses import dataclass, field
from typing import Protocol


class QALoop(Protocol):
    def ask_user(
        self,
        *,
        template_name: str,
        context: dict,
        adapter_name: str,
        adapter_state: dict,
    ) -> str: ...


@dataclass
class StubQALoop:
    """Stub: returns a pre-canned answer or 'PENDING' if not configured.

    Signature matches the real QALoopAPI.ask_user (plan 6) so the stub is
    drop-in replaceable.
    """
    canned_answers: dict[str, str] = field(default_factory=dict)
    calls: list[tuple[str, dict]] = field(default_factory=list)

    def ask_user(
        self,
        *,
        template_name: str,
        context: dict,
        adapter_name: str = "stub-process",
        adapter_state: dict | None = None,
    ) -> str:
        self.calls.append((template_name, context))
        return self.canned_answers.get(template_name, "PENDING")
```

- [ ] **Step 4: Run tests** — Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/rufino/engine/process/context_injectors.py src/rufino/engine/process/qa_integration.py tests/test_process_context_injectors.py
git commit -m "feat(process): context injectors + Q&A stub for dispatcher"
```

---

## Task 7: Dispatcher — light mode

**Files:**
- Create: `src/rufino/engine/process/dispatcher.py`
- Create: `tests/test_process_dispatcher_light.py`

- [ ] **Step 1: Failing test**

`tests/test_process_dispatcher_light.py`:
```python
from pathlib import Path
from rufino.engine.process.dispatcher import process_note, ProcessResult


def test_light_mode_updates_indices_only(tmp_vault: Path):
    inbox = tmp_vault / "inbox"
    inbox.mkdir()
    note = inbox / "test.md"
    note.write_text(
        "---\n"
        "tags: [materia/ml-i, tema/regresion]\n"
        "triples:\n"
        "  - { r: tema-de, o: ml-i }\n"
        "---\n"
        "Body unchanged.\n"
    )

    (tmp_vault / "_meta").mkdir()
    (tmp_vault / "_meta" / "_tags.md").write_text("# Tags\n")
    (tmp_vault / "_meta" / "_processing-log.md").write_text("# Log\n")

    result = process_note(
        note_path=note,
        vault_root=tmp_vault,
        mode="light",
    )

    assert result.success
    # Body is unchanged in light mode
    assert "Body unchanged." in note.read_text()
    # Tag index now references the note
    tag_index = (tmp_vault / "_meta" / "_tags.md").read_text()
    assert "materia/ml-i" in tag_index
```

- [ ] **Step 2: Run (fails)**

- [ ] **Step 3: Implement (light mode only first)**

`src/rufino/engine/process/dispatcher.py`:
```python
from dataclasses import dataclass
from pathlib import Path
from rufino.engine.process.helpers.frontmatter import parse_frontmatter
from rufino.engine.process.helpers.indices import update_tag_index, append_to_log


@dataclass
class ProcessResult:
    success: bool
    note_path: Path
    message: str = ""


def process_note(
    *,
    note_path: Path,
    vault_root: Path,
    mode: str,
) -> ProcessResult:
    """Process a note. Modes: light (indices only), full (LLM augment), lint (validate)."""
    if mode == "light":
        return _process_light(note_path=note_path, vault_root=vault_root)
    raise NotImplementedError(f"Mode {mode!r} not implemented yet (Task 8 covers full)")


def _process_light(*, note_path: Path, vault_root: Path) -> ProcessResult:
    text = note_path.read_text()
    fm, _body = parse_frontmatter(text)
    tags = fm.get("tags", [])

    tag_index = vault_root / "_meta" / "_tags.md"
    note_slug = note_path.stem
    for tag in tags:
        update_tag_index(tag_index, tag=tag, note_slug=note_slug)

    log = vault_root / "_meta" / "_processing-log.md"
    append_to_log(log, message=f"light-processed {note_slug}")

    return ProcessResult(success=True, note_path=note_path, message="light OK")
```

- [ ] **Step 4: Run tests** — Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add src/rufino/engine/process/dispatcher.py tests/test_process_dispatcher_light.py
git commit -m "feat(process): dispatcher with light mode (indices only)"
```

---

## Task 8: Dispatcher — full mode with LLM call

**Files:**
- Modify: `src/rufino/engine/process/dispatcher.py`
- Create: `tests/test_process_dispatcher_full.py`
- Create: `tests/fixtures/adapters/process-apunte-clase/manifest.yaml`
- Create: `tests/fixtures/adapters/process-apunte-clase/prompt.md`

- [ ] **Step 1: Create adapter fixture**

`tests/fixtures/adapters/process-apunte-clase/manifest.yaml`:
```yaml
adapter_name: apunte-clase
note_type: apunte_clase
applies_when:
  source_dir: inbox/
  matches_pattern: ["*.md", "*.txt"]
llm: sonnet
mode_default: full
output_schema:
  required:
    materia: { type: string }
    topics: list[str]
  optional:
    profesor: persona_ref
triple_vocabulary: [tema-de, expuesto-por]
tag_axes:
  - { axis: materia, format: "materia/<slug>", required: true }
  - { axis: tema, format: "tema/<slug>", min: 1 }
destination_path: "apuntes/{materia}/{slug}.md"
qa_triggers: []
context_injectors:
  - { name: apuntes_previos, query: "tag=materia/<materia>" }
```

`tests/fixtures/adapters/process-apunte-clase/prompt.md`:
```markdown
Procesá este apunte.

## Apunte
{{note_body}}

## Apuntes previos
{{context.apuntes_previos}}

## Output esperado
Markdown con frontmatter completo.
```

- [ ] **Step 2: Failing test**

`tests/test_process_dispatcher_full.py`:
```python
from pathlib import Path
from rufino.engine.process.dispatcher import process_note
from rufino.engine.process.llm_client import StubLLMClient
from rufino.engine.process.context_injectors import StubQueryLayer
from rufino.engine.process.qa_integration import StubQALoop


FIXTURE = Path(__file__).parent / "fixtures" / "adapters" / "process-apunte-clase"


CANNED_LLM_OUTPUT = """---
materia: ml-i
topics: [regresion, gradient-descent]
profesor: mendez
triples:
  - { r: tema-de, o: ml-i }
  - { r: expuesto-por, o: mendez }
tags: [materia/ml-i, tema/regresion, profesor/mendez]
---
Body augmentado.
"""


def test_full_mode_writes_augmented_to_destination(tmp_vault: Path):
    inbox = tmp_vault / "inbox"
    inbox.mkdir()
    note = inbox / "clase3.md"
    note.write_text("Crude apunte sobre regresión logística.")

    (tmp_vault / "_meta").mkdir()
    (tmp_vault / "_meta" / "_tags.md").write_text("# Tags\n")
    (tmp_vault / "_meta" / "_processing-log.md").write_text("# Log\n")

    result = process_note(
        note_path=note,
        vault_root=tmp_vault,
        mode="full",
        adapter_dir=FIXTURE,
        llm_client=StubLLMClient(canned_response=CANNED_LLM_OUTPUT),
        query_layer=StubQueryLayer(),
        qa_loop=StubQALoop(),
    )

    assert result.success, result.message
    destination = tmp_vault / "apuntes" / "ml-i" / "clase3.md"
    assert destination.exists()
    assert "Body augmentado" in destination.read_text()
    assert not note.exists()  # moved
```

- [ ] **Step 3: Run (fails)**

- [ ] **Step 4: Implement full mode**

Modify `src/rufino/engine/process/dispatcher.py` — add `_process_full` and update `process_note`:

```python
from rufino.engine.process.manifest import parse_worker_manifest
from rufino.engine.process.helpers.frontmatter import parse_frontmatter, validate_against_schema, render_frontmatter
from rufino.engine.process.helpers.triples import extract_triples, validate_triples_against_vocab
from rufino.engine.process.context_injectors import apply_context_injectors


def process_note(
    *,
    note_path: Path,
    vault_root: Path,
    mode: str,
    adapter_dir: Path | None = None,
    llm_client=None,
    query_layer=None,
    qa_loop=None,
) -> ProcessResult:
    if mode == "light":
        return _process_light(note_path=note_path, vault_root=vault_root)
    if mode == "full":
        if adapter_dir is None or llm_client is None or query_layer is None or qa_loop is None:
            raise ValueError("full mode requires adapter_dir, llm_client, query_layer, qa_loop")
        return _process_full(
            note_path=note_path,
            vault_root=vault_root,
            adapter_dir=adapter_dir,
            llm_client=llm_client,
            query_layer=query_layer,
            qa_loop=qa_loop,
        )
    raise NotImplementedError(f"Mode {mode!r} not implemented")


def _process_full(
    *, note_path, vault_root, adapter_dir, llm_client, query_layer, qa_loop,
) -> ProcessResult:
    manifest = parse_worker_manifest((adapter_dir / "manifest.yaml").read_text())
    prompt_template = (adapter_dir / "prompt.md").read_text()

    body = note_path.read_text()

    # Best-effort: parse current frontmatter for variables to inject
    current_fm, current_body = parse_frontmatter(body)
    variables = {k: v for k, v in current_fm.items() if isinstance(v, str)}

    context = apply_context_injectors(
        injectors=list(manifest.context_injectors),
        variables=variables,
        query=query_layer,
    )

    # Render prompt with simple {{...}} substitution
    rendered = prompt_template.replace("{{note_body}}", current_body)
    for key, val in context.items():
        rendered = rendered.replace(f"{{{{context.{key}}}}}", val)

    llm_response = llm_client.complete(prompt=rendered, model=manifest.llm)

    augmented_fm, augmented_body = parse_frontmatter(llm_response.text)

    validate_against_schema(augmented_fm, manifest.output_schema)
    triples = extract_triples(augmented_fm)
    validate_triples_against_vocab(triples, set(manifest.triple_vocabulary))

    # Render destination path
    dest_rel = manifest.destination_path.format(
        slug=note_path.stem,
        **{k: v for k, v in augmented_fm.items() if isinstance(v, str)},
    )
    dest = vault_root / dest_rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(render_frontmatter(augmented_fm, augmented_body))
    note_path.unlink()  # moved

    # Update indices (delegate to light helpers)
    from rufino.engine.process.helpers.indices import update_tag_index, append_to_log
    tag_index = vault_root / "_meta" / "_tags.md"
    for tag in augmented_fm.get("tags", []):
        update_tag_index(tag_index, tag=tag, note_slug=note_path.stem)
    append_to_log(vault_root / "_meta" / "_processing-log.md",
                  message=f"full-processed {note_path.stem} → {dest_rel}")

    return ProcessResult(success=True, note_path=dest, message=f"moved to {dest_rel}")
```

- [ ] **Step 5: Run tests** — Expected: full mode test passes, light mode still passes

Run: `pytest tests/test_process_dispatcher_*.py -v`

- [ ] **Step 6: Commit**

```bash
git add src/rufino/engine/process/dispatcher.py tests/test_process_dispatcher_full.py tests/fixtures/adapters/process-apunte-clase/
git commit -m "feat(process): full mode dispatcher with LLM call + adapter integration"
```

---

## Task 9: CLI command `rufino process <note_path>`

**Files:**
- Modify: `src/rufino/cli.py`
- Create: `tests/test_cli_process.py`

- [ ] **Step 1: Failing test**

`tests/test_cli_process.py`:
```python
from pathlib import Path
from click.testing import CliRunner
from rufino.cli import cli


def test_process_light_via_cli(tmp_vault: Path):
    inbox = tmp_vault / "inbox"
    inbox.mkdir()
    note = inbox / "n.md"
    note.write_text(
        "---\ntags: [materia/ml-i]\n---\nBody\n"
    )
    (tmp_vault / "_meta").mkdir()
    (tmp_vault / "_meta" / "_tags.md").write_text("# Tags\n")
    (tmp_vault / "_meta" / "_processing-log.md").write_text("# Log\n")

    runner = CliRunner()
    result = runner.invoke(cli, [
        "process", str(note),
        "--vault", str(tmp_vault),
        "--mode", "light",
    ])
    assert result.exit_code == 0, result.output
    assert "materia/ml-i" in (tmp_vault / "_meta" / "_tags.md").read_text()
```

- [ ] **Step 2: Run (fails)**

- [ ] **Step 3: Append to `src/rufino/cli.py`**

```python
from rufino.engine.process.dispatcher import process_note as _process_note


@cli.command(name="process")
@click.argument("note_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--vault", "vault_root", required=True, type=click.Path(path_type=Path),
              help="Vault root path")
@click.option("--mode", default="light", type=click.Choice(["light", "full", "lint"]))
@click.option("--adapter-dir", type=click.Path(path_type=Path),
              help="Required for --mode full")
def process_cmd(note_path: Path, vault_root: Path, mode: str, adapter_dir: Path | None) -> None:
    """Process a single note. v1 supports light mode without an adapter."""
    if mode == "full" and adapter_dir is None:
        click.echo("Error: --adapter-dir required for --mode full", err=True)
        raise click.exceptions.Exit(code=1)
    if mode == "full":
        # CLI invocation of full mode wires real backends in plan 7+ (Query layer, real LLM).
        # For now, fail clearly if invoked from CLI.
        click.echo("Error: full mode CLI wiring lands in plan 7 (needs real LLM + Query)", err=True)
        raise click.exceptions.Exit(code=2)
    result = _process_note(note_path=note_path, vault_root=vault_root, mode=mode)
    click.echo(f"{result.message}")
```

- [ ] **Step 4: Run tests** — Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add src/rufino/cli.py tests/test_cli_process.py
git commit -m "feat(process): CLI command 'rufino process' (light mode wired)"
```

---

## Task 10: End-to-end smoke

**Files:**
- Create: `tests/test_process_smoke.py`

- [ ] **Step 1: Smoke test**

`tests/test_process_smoke.py`:
```python
from pathlib import Path
from rufino.engine.process.dispatcher import process_note
from rufino.engine.process.llm_client import StubLLMClient
from rufino.engine.process.context_injectors import StubQueryLayer
from rufino.engine.process.qa_integration import StubQALoop


FIXTURE = Path(__file__).parent / "fixtures" / "adapters" / "process-apunte-clase"


def test_full_process_pipeline_end_to_end(tmp_vault: Path):
    inbox = tmp_vault / "inbox"
    inbox.mkdir()
    note = inbox / "smoke.md"
    note.write_text("Apunte crudo de smoke test.")

    (tmp_vault / "_meta").mkdir()
    (tmp_vault / "_meta" / "_tags.md").write_text("# Tags\n")
    (tmp_vault / "_meta" / "_processing-log.md").write_text("# Log\n")

    canned = """---
materia: ml-i
topics: [smoke]
triples:
  - { r: tema-de, o: ml-i }
tags: [materia/ml-i, tema/smoke]
---
Augmentado smoke.
"""
    result = process_note(
        note_path=note,
        vault_root=tmp_vault,
        mode="full",
        adapter_dir=FIXTURE,
        llm_client=StubLLMClient(canned_response=canned),
        query_layer=StubQueryLayer(),
        qa_loop=StubQALoop(),
    )

    assert result.success
    moved = tmp_vault / "apuntes" / "ml-i" / "smoke.md"
    assert moved.exists()
    assert "Augmentado smoke" in moved.read_text()
    assert "materia/ml-i" in (tmp_vault / "_meta" / "_tags.md").read_text()
```

- [ ] **Step 2: Run**

Run: `pytest tests/test_process_smoke.py -v`
Expected: 1 passed

- [ ] **Step 3: Run full suite to check no regression**

Run: `pytest -v`
Expected: all pass

- [ ] **Step 4: Commit**

```bash
git add tests/test_process_smoke.py
git commit -m "test(process): end-to-end pipeline smoke (crude → augmented → moved)"
```

---

## Self-review checklist

- [ ] Manifest parser rejects all invalid cases tested
- [ ] Frontmatter helpers handle notes both with and without frontmatter
- [ ] Triple validator rejects unknown relations
- [ ] Concept promotion is idempotent (no overwrite of existing pages)
- [ ] Person registration is idempotent
- [ ] Dispatcher light mode does NOT call LLM
- [ ] Dispatcher full mode validates output against schema + vocab before move
- [ ] CLI rejects `--mode full` without `--adapter-dir`

## Done criteria

- `pytest tests/test_process_*.py -v` all pass
- `./cli/rufino process <note> --vault X --mode light` updates `_meta/_tags.md` and `_meta/_processing-log.md`
- Smoke test moves a crude note from `inbox/` to `apuntes/<materia>/` and renders augmented content
