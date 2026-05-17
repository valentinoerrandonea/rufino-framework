# Plan 4 — Ingest engine primitive Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementar la primitive Ingest con sus 3 output modes (`emit_fact`, `import_raw`, `emit_augmented`), helpers de cursor/dedup, validación de fact_schema, y trigger push inmediato a Process cuando `import_raw`. Al final, un adapter `ingest-belo` puede traer transacciones simuladas, escribir facts idempotentes en el vault, y un adapter `ingest-drive-pdfs` puede importar un PDF a inbox e invocar Process al toque.

**Architecture:** Cada adapter declara su `fetch(since) → [fact]` como una función Python en el adapter dir (`fetcher.py`). El runner del framework carga el adapter dinámicamente, llama `fetch`, valida cada fact contra `fact_schema` declarado, deduplica por `dedup_by`, escribe a destino según `output_mode`. Para `import_raw`, después de escribir invoca Process dispatcher con el `process_with` declarado.

**Tech Stack:** Python 3.11+, importlib (carga dinámica de adapters), pyyaml. OAuth real se mockea en tests con `StubFetcher`.

**Dependencias previas:** Plan 1 (Foundation), Plan 3 (Process — invocado en import_raw mode).

**Plans que dependen de este:** Plan 8 (Wizard genera adapters de Ingest).

---

## File Structure

```
src/rufino/engine/ingest/
├── __init__.py
├── manifest.py             # IngestAdapterManifest + parser
├── validator.py            # IngestAdapterValidator
├── runner.py               # ingest(adapter_name) entrypoint
├── cursor.py               # CursorStore (per-adapter last-processed marker)
├── dedup.py                # dedup_check via SQLite per source
├── fact_schema.py          # validate fact dict against declared schema
└── fetcher_loader.py       # importlib-based loader for adapter's fetcher.py
src/rufino/cli.py           # MODIFY: `rufino ingest <adapter_name>`
tests/test_ingest_*.py
tests/fixtures/adapters/ingest-belo/
├── manifest.yaml
└── fetcher.py              # StubFetcher returning canned transactions
tests/fixtures/adapters/ingest-drive-pdfs/
├── manifest.yaml
└── fetcher.py              # StubFetcher returning a fake PDF path
```

---

## Task 1: Ingest manifest parser

**Files:**
- Create: `src/rufino/engine/ingest/__init__.py`
- Create: `src/rufino/engine/ingest/manifest.py`
- Create: `tests/test_ingest_manifest.py`

- [ ] **Step 1: Failing test**

`tests/test_ingest_manifest.py`:
```python
import pytest
from rufino.engine.ingest.manifest import (
    IngestAdapterManifest,
    parse_ingest_manifest,
    ManifestParseError,
)


EMIT_FACT_YAML = """
adapter_name: belo
source_name: belo
schedule: "*/30 * * * *"
auth:
  type: oauth2
  keychain_service: rufino-belo-oauth
output_mode: emit_fact
emits: [transaccion]
fact_schema:
  id: string
  monto: number
  moneda: enum[ARS, USD]
destination:
  facts: belo/facts/<YYYY-MM-DD>-<id>.md
  raw: belo/raw/<id>.json
dedup_by: id
"""

IMPORT_RAW_YAML = """
adapter_name: drive-pdfs
source_name: drive_pdfs
schedule: "0 */6 * * *"
auth:
  type: oauth2
  keychain_service: rufino-drive
output_mode: import_raw
target_inbox: rufino/inbox/
process_with: apunte-clase
trigger: immediate
"""


def test_parses_emit_fact():
    m = parse_ingest_manifest(EMIT_FACT_YAML)
    assert m.output_mode == "emit_fact"
    assert m.dedup_by == "id"
    assert m.fact_schema["monto"] == "number"


def test_parses_import_raw():
    m = parse_ingest_manifest(IMPORT_RAW_YAML)
    assert m.output_mode == "import_raw"
    assert m.target_inbox == "rufino/inbox/"
    assert m.process_with == "apunte-clase"
    assert m.trigger == "immediate"


def test_invalid_output_mode_raises():
    yaml = EMIT_FACT_YAML.replace("output_mode: emit_fact", "output_mode: bogus")
    with pytest.raises(ManifestParseError, match="output_mode"):
        parse_ingest_manifest(yaml)


def test_import_raw_missing_process_with_raises():
    yaml = IMPORT_RAW_YAML.replace("process_with: apunte-clase\n", "")
    with pytest.raises(ManifestParseError, match="process_with"):
        parse_ingest_manifest(yaml)
```

- [ ] **Step 2: Run (fails)**

- [ ] **Step 3: Implement**

`src/rufino/engine/ingest/__init__.py`: `` (empty)

`src/rufino/engine/ingest/manifest.py`:
```python
from dataclasses import dataclass
from typing import Any
import yaml


class ManifestParseError(Exception):
    """Raised when ingest adapter manifest is invalid."""


VALID_OUTPUT_MODES = {"emit_fact", "import_raw", "emit_augmented"}
VALID_TRIGGERS = {"immediate", "defer"}


@dataclass(frozen=True)
class IngestAdapterManifest:
    adapter_name: str
    source_name: str
    schedule: str
    auth: dict[str, Any]
    output_mode: str  # emit_fact | import_raw | emit_augmented
    # emit_fact-specific:
    emits: tuple[str, ...] = ()
    fact_schema: dict[str, Any] = None  # type: ignore
    destination_facts: str | None = None
    destination_raw: str | None = None
    dedup_by: str | None = None
    # import_raw-specific:
    target_inbox: str | None = None
    process_with: str | None = None
    trigger: str = "immediate"
    # emit_augmented-specific:
    process_inline_with: str | None = None
    # shared optional:
    transform_hook: str | None = None


_REQUIRED_SHARED = ("adapter_name", "source_name", "schedule", "output_mode")


def parse_ingest_manifest(yaml_text: str) -> IngestAdapterManifest:
    try:
        raw = yaml.safe_load(yaml_text)
    except yaml.YAMLError as e:
        raise ManifestParseError(f"Invalid YAML: {e}") from e

    if not isinstance(raw, dict):
        raise ManifestParseError("Manifest root must be a mapping")

    missing = [f for f in _REQUIRED_SHARED if f not in raw]
    if missing:
        raise ManifestParseError(f"Missing required fields: {missing}")

    mode = raw["output_mode"]
    if mode not in VALID_OUTPUT_MODES:
        raise ManifestParseError(
            f"output_mode must be one of {VALID_OUTPUT_MODES}, got {mode!r}"
        )

    common = dict(
        adapter_name=raw["adapter_name"],
        source_name=raw["source_name"],
        schedule=raw["schedule"],
        auth=raw.get("auth", {}),
        output_mode=mode,
        transform_hook=raw.get("transform_hook"),
    )

    if mode == "emit_fact":
        for f in ("emits", "fact_schema", "destination", "dedup_by"):
            if f not in raw:
                raise ManifestParseError(f"emit_fact requires field {f!r}")
        dest = raw["destination"]
        return IngestAdapterManifest(
            **common,
            emits=tuple(raw["emits"]),
            fact_schema=raw["fact_schema"],
            destination_facts=dest.get("facts"),
            destination_raw=dest.get("raw"),
            dedup_by=raw["dedup_by"],
        )

    if mode == "import_raw":
        for f in ("target_inbox", "process_with"):
            if f not in raw:
                raise ManifestParseError(f"import_raw requires field {f!r}")
        trigger = raw.get("trigger", "immediate")
        if trigger not in VALID_TRIGGERS:
            raise ManifestParseError(f"trigger must be one of {VALID_TRIGGERS}")
        return IngestAdapterManifest(
            **common,
            target_inbox=raw["target_inbox"],
            process_with=raw["process_with"],
            trigger=trigger,
        )

    # emit_augmented
    if "process_inline_with" not in raw:
        raise ManifestParseError("emit_augmented requires process_inline_with")
    return IngestAdapterManifest(
        **common,
        process_inline_with=raw["process_inline_with"],
    )
```

- [ ] **Step 4: Run tests** — Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/rufino/engine/ingest/ tests/test_ingest_manifest.py
git commit -m "feat(ingest): manifest parser with 3 output modes"
```

---

## Task 2: Cursor persistence (per-adapter)

**Files:**
- Create: `src/rufino/engine/ingest/cursor.py`
- Create: `tests/test_ingest_cursor.py`

- [ ] **Step 1: Failing test**

`tests/test_ingest_cursor.py`:
```python
from pathlib import Path
from rufino.engine.ingest.cursor import CursorStore


def test_cursor_initial_is_none(tmp_path: Path):
    store = CursorStore(tmp_path / "cursors.json")
    assert store.get("belo") is None


def test_cursor_set_and_get(tmp_path: Path):
    store = CursorStore(tmp_path / "cursors.json")
    store.set("belo", "2026-05-16T10:00:00Z")
    assert store.get("belo") == "2026-05-16T10:00:00Z"


def test_cursor_persists(tmp_path: Path):
    p = tmp_path / "cursors.json"
    s1 = CursorStore(p)
    s1.set("belo", "X")
    s2 = CursorStore(p)
    assert s2.get("belo") == "X"
```

- [ ] **Step 2: Run (fails)**

- [ ] **Step 3: Implement**

`src/rufino/engine/ingest/cursor.py`:
```python
import json
from pathlib import Path


class CursorStore:
    """Per-adapter cursor (last-processed marker). Persisted as JSON."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._data: dict[str, str] = {}
        if path.exists():
            self._data = json.loads(path.read_text())

    def get(self, adapter_name: str) -> str | None:
        return self._data.get(adapter_name)

    def set(self, adapter_name: str, cursor: str) -> None:
        self._data[adapter_name] = cursor
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, indent=2))
```

- [ ] **Step 4: Run tests** — Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/rufino/engine/ingest/cursor.py tests/test_ingest_cursor.py
git commit -m "feat(ingest): per-adapter cursor persistence"
```

---

## Task 3: Dedup check (SQLite-backed)

**Files:**
- Create: `src/rufino/engine/ingest/dedup.py`
- Create: `tests/test_ingest_dedup.py`

- [ ] **Step 1: Failing test**

`tests/test_ingest_dedup.py`:
```python
from pathlib import Path
from rufino.engine.ingest.dedup import DedupStore


def test_first_seen_returns_true_then_false(tmp_path: Path):
    store = DedupStore(tmp_path / "dedup.sqlite")
    assert store.is_new(source="belo", fact_id="tx-1") is True
    store.mark_seen(source="belo", fact_id="tx-1")
    assert store.is_new(source="belo", fact_id="tx-1") is False


def test_different_sources_isolated(tmp_path: Path):
    store = DedupStore(tmp_path / "dedup.sqlite")
    store.mark_seen(source="belo", fact_id="tx-1")
    assert store.is_new(source="mp", fact_id="tx-1") is True


def test_persists_across_instances(tmp_path: Path):
    p = tmp_path / "dedup.sqlite"
    DedupStore(p).mark_seen(source="belo", fact_id="x")
    assert DedupStore(p).is_new(source="belo", fact_id="x") is False
```

- [ ] **Step 2: Run (fails)**

- [ ] **Step 3: Implement**

`src/rufino/engine/ingest/dedup.py`:
```python
import sqlite3
from pathlib import Path


class DedupStore:
    """SQLite-backed dedup tracking per source."""

    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS seen (source TEXT, fact_id TEXT, PRIMARY KEY(source, fact_id))"
        )
        self._conn.commit()

    def is_new(self, *, source: str, fact_id: str) -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM seen WHERE source = ? AND fact_id = ?",
            (source, fact_id),
        )
        return cur.fetchone() is None

    def mark_seen(self, *, source: str, fact_id: str) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO seen (source, fact_id) VALUES (?, ?)",
            (source, fact_id),
        )
        self._conn.commit()
```

- [ ] **Step 4: Run tests** — Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/rufino/engine/ingest/dedup.py tests/test_ingest_dedup.py
git commit -m "feat(ingest): SQLite-backed dedup per source"
```

---

## Task 4: Fact schema validator

**Files:**
- Create: `src/rufino/engine/ingest/fact_schema.py`
- Create: `tests/test_ingest_fact_schema.py`

- [ ] **Step 1: Failing test**

`tests/test_ingest_fact_schema.py`:
```python
import pytest
from rufino.engine.ingest.fact_schema import validate_fact, FactSchemaError


SCHEMA = {
    "id": "string",
    "monto": "number",
    "moneda": "enum[ARS, USD]",
}


def test_valid_fact_passes():
    validate_fact({"id": "x", "monto": 100, "moneda": "ARS"}, schema=SCHEMA)


def test_missing_field_raises():
    with pytest.raises(FactSchemaError, match="monto"):
        validate_fact({"id": "x", "moneda": "ARS"}, schema=SCHEMA)


def test_wrong_type_raises():
    with pytest.raises(FactSchemaError, match="number"):
        validate_fact({"id": "x", "monto": "not a number", "moneda": "ARS"}, schema=SCHEMA)


def test_enum_violation_raises():
    with pytest.raises(FactSchemaError, match="enum"):
        validate_fact({"id": "x", "monto": 1, "moneda": "BTC"}, schema=SCHEMA)
```

- [ ] **Step 2: Run (fails)**

- [ ] **Step 3: Implement**

`src/rufino/engine/ingest/fact_schema.py`:
```python
import re
from typing import Any


class FactSchemaError(Exception):
    """Raised when a fact does not match its declared schema."""


_ENUM_RE = re.compile(r"^enum\[(.+)\]$")


def validate_fact(fact: dict[str, Any], *, schema: dict[str, str]) -> None:
    for field_name, type_spec in schema.items():
        if field_name not in fact:
            raise FactSchemaError(f"Required field missing: {field_name}")
        value = fact[field_name]
        _check_type(field_name, value, type_spec)


def _check_type(field: str, value: Any, type_spec: str) -> None:
    if type_spec == "string":
        if not isinstance(value, str):
            raise FactSchemaError(f"{field}: expected string, got {type(value).__name__}")
    elif type_spec == "number":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise FactSchemaError(f"{field}: expected number, got {type(value).__name__}")
    elif type_spec == "datetime":
        if not isinstance(value, str):
            raise FactSchemaError(f"{field}: expected datetime string, got {type(value).__name__}")
    elif (m := _ENUM_RE.match(type_spec)):
        options = [s.strip() for s in m.group(1).split(",")]
        if value not in options:
            raise FactSchemaError(f"{field}: expected enum {options}, got {value!r}")
    else:
        # Unknown type spec — pass for now, plan upgrade can add stricter checks
        pass
```

- [ ] **Step 4: Run tests** — Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/rufino/engine/ingest/fact_schema.py tests/test_ingest_fact_schema.py
git commit -m "feat(ingest): fact schema validator"
```

---

## Task 5: Fetcher loader (importlib-based)

**Files:**
- Create: `src/rufino/engine/ingest/fetcher_loader.py`
- Create: `tests/fixtures/adapters/ingest-belo/manifest.yaml`
- Create: `tests/fixtures/adapters/ingest-belo/fetcher.py`
- Create: `tests/test_ingest_fetcher_loader.py`

- [ ] **Step 1: Create fixture adapter**

`tests/fixtures/adapters/ingest-belo/manifest.yaml`:
```yaml
adapter_name: belo
source_name: belo
schedule: "*/30 * * * *"
auth:
  type: oauth2
  keychain_service: rufino-belo-oauth
output_mode: emit_fact
emits: [transaccion]
fact_schema:
  id: string
  monto: number
  moneda: enum[ARS, USD, USDT]
  fecha: datetime
destination:
  facts: belo/facts/<YYYY-MM-DD>-<id>.md
  raw: belo/raw/<id>.json
dedup_by: id
```

`tests/fixtures/adapters/ingest-belo/fetcher.py`:
```python
"""Stub fetcher returning canned transactions for tests."""

CANNED = [
    {"id": "tx-001", "monto": 100.0, "moneda": "ARS", "fecha": "2026-05-16T10:00:00Z"},
    {"id": "tx-002", "monto": 50.0, "moneda": "USD", "fecha": "2026-05-16T11:00:00Z"},
]


def fetch(since: str | None) -> list[dict]:
    """Return all canned facts. `since` is ignored in this stub."""
    return CANNED
```

- [ ] **Step 2: Failing test**

`tests/test_ingest_fetcher_loader.py`:
```python
from pathlib import Path
from rufino.engine.ingest.fetcher_loader import load_fetcher


FIXTURE = Path(__file__).parent / "fixtures" / "adapters" / "ingest-belo"


def test_load_fetcher_returns_callable():
    fetcher = load_fetcher(FIXTURE)
    assert callable(fetcher)


def test_loaded_fetcher_returns_facts():
    fetcher = load_fetcher(FIXTURE)
    facts = fetcher(since=None)
    assert len(facts) == 2
    assert facts[0]["id"] == "tx-001"
```

- [ ] **Step 3: Run (fails)**

- [ ] **Step 4: Implement**

`src/rufino/engine/ingest/fetcher_loader.py`:
```python
import importlib.util
from pathlib import Path
from typing import Callable


def load_fetcher(adapter_dir: Path) -> Callable:
    """Load adapter_dir/fetcher.py and return its `fetch` function."""
    fetcher_path = adapter_dir / "fetcher.py"
    if not fetcher_path.exists():
        raise FileNotFoundError(f"No fetcher.py in {adapter_dir}")

    spec = importlib.util.spec_from_file_location(
        f"rufino_adapter_{adapter_dir.name}", fetcher_path
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load fetcher.py at {fetcher_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    if not hasattr(module, "fetch") or not callable(module.fetch):
        raise AttributeError(f"{fetcher_path} does not define a callable `fetch`")
    return module.fetch
```

- [ ] **Step 5: Run tests** — Expected: 2 passed

- [ ] **Step 6: Commit**

```bash
git add src/rufino/engine/ingest/fetcher_loader.py tests/fixtures/adapters/ingest-belo/ tests/test_ingest_fetcher_loader.py
git commit -m "feat(ingest): dynamic loader for adapter fetcher.py"
```

---

## Task 6: Runner — emit_fact mode

**Files:**
- Create: `src/rufino/engine/ingest/runner.py`
- Create: `tests/test_ingest_runner_emit_fact.py`

- [ ] **Step 1: Failing test**

`tests/test_ingest_runner_emit_fact.py`:
```python
from pathlib import Path
from rufino.engine.ingest.runner import run_ingest, IngestResult


FIXTURE = Path(__file__).parent / "fixtures" / "adapters" / "ingest-belo"


def test_emit_fact_writes_facts_to_vault(tmp_vault: Path, tmp_path: Path):
    result = run_ingest(
        adapter_dir=FIXTURE,
        vault_root=tmp_vault,
        rufino_state_dir=tmp_path / ".rufino-state",
    )

    assert isinstance(result, IngestResult)
    assert result.facts_emitted == 2

    facts_dir = tmp_vault / "belo" / "facts"
    fact_files = list(facts_dir.glob("*.md"))
    assert len(fact_files) == 2


def test_emit_fact_dedup_on_rerun(tmp_vault: Path, tmp_path: Path):
    state = tmp_path / ".rufino-state"
    run_ingest(adapter_dir=FIXTURE, vault_root=tmp_vault, rufino_state_dir=state)
    result_2 = run_ingest(adapter_dir=FIXTURE, vault_root=tmp_vault, rufino_state_dir=state)
    assert result_2.facts_emitted == 0  # all deduped
    assert result_2.facts_skipped == 2
```

- [ ] **Step 2: Run (fails)**

- [ ] **Step 3: Implement**

`src/rufino/engine/ingest/runner.py`:
```python
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from rufino.engine.ingest.manifest import parse_ingest_manifest
from rufino.engine.ingest.cursor import CursorStore
from rufino.engine.ingest.dedup import DedupStore
from rufino.engine.ingest.fact_schema import validate_fact, FactSchemaError
from rufino.engine.ingest.fetcher_loader import load_fetcher


@dataclass
class IngestResult:
    adapter_name: str
    facts_emitted: int
    facts_skipped: int
    errors: list[str]


def run_ingest(
    *,
    adapter_dir: Path,
    vault_root: Path,
    rufino_state_dir: Path,
) -> IngestResult:
    """Run an Ingest adapter. Dispatches to mode-specific subroutine."""
    manifest = parse_ingest_manifest((adapter_dir / "manifest.yaml").read_text())

    if manifest.output_mode == "emit_fact":
        return _run_emit_fact(
            adapter_dir=adapter_dir,
            manifest=manifest,
            vault_root=vault_root,
            rufino_state_dir=rufino_state_dir,
        )
    if manifest.output_mode == "import_raw":
        return _run_import_raw(
            adapter_dir=adapter_dir,
            manifest=manifest,
            vault_root=vault_root,
            rufino_state_dir=rufino_state_dir,
        )
    raise NotImplementedError(f"output_mode {manifest.output_mode} not implemented")


def _render_dest(template: str, *, fact: dict, today: str) -> str:
    return (
        template
        .replace("<YYYY-MM-DD>", today)
        .replace("<id>", fact["id"])
    )


def _run_emit_fact(
    *, adapter_dir: Path, manifest, vault_root: Path, rufino_state_dir: Path,
) -> IngestResult:
    fetcher = load_fetcher(adapter_dir)
    cursors = CursorStore(rufino_state_dir / "cursors.json")
    dedup = DedupStore(rufino_state_dir / "dedup.sqlite")

    since = cursors.get(manifest.adapter_name)
    facts = fetcher(since=since)

    today = datetime.utcnow().strftime("%Y-%m-%d")
    emitted = 0
    skipped = 0
    errors: list[str] = []

    for fact in facts:
        try:
            validate_fact(fact, schema=manifest.fact_schema)
        except FactSchemaError as e:
            errors.append(f"schema violation: {e}")
            continue

        fact_id = fact[manifest.dedup_by]
        if not dedup.is_new(source=manifest.source_name, fact_id=fact_id):
            skipped += 1
            continue

        fact_path = vault_root / _render_dest(manifest.destination_facts, fact=fact, today=today)
        raw_path = vault_root / _render_dest(manifest.destination_raw, fact=fact, today=today)

        fact_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.parent.mkdir(parents=True, exist_ok=True)

        fact_md = (
            f"---\nsource: {manifest.source_name}\nfact_id: {fact_id}\n"
            + "\n".join(f"{k}: {v!r}" for k, v in fact.items())
            + "\n---\n"
        )
        fact_path.write_text(fact_md)
        raw_path.write_text(json.dumps(fact, indent=2))

        dedup.mark_seen(source=manifest.source_name, fact_id=fact_id)
        emitted += 1

    cursors.set(manifest.adapter_name, datetime.utcnow().isoformat() + "Z")

    return IngestResult(
        adapter_name=manifest.adapter_name,
        facts_emitted=emitted,
        facts_skipped=skipped,
        errors=errors,
    )


def _run_import_raw(
    *, adapter_dir: Path, manifest, vault_root: Path, rufino_state_dir: Path,
) -> IngestResult:
    raise NotImplementedError("import_raw lands in Task 7")
```

- [ ] **Step 4: Run tests** — Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/rufino/engine/ingest/runner.py tests/test_ingest_runner_emit_fact.py
git commit -m "feat(ingest): runner for emit_fact mode with dedup + cursor"
```

---

## Task 7: Runner — import_raw mode with push to Process

**Files:**
- Modify: `src/rufino/engine/ingest/runner.py`
- Create: `tests/fixtures/adapters/ingest-drive-pdfs/manifest.yaml`
- Create: `tests/fixtures/adapters/ingest-drive-pdfs/fetcher.py`
- Create: `tests/test_ingest_runner_import_raw.py`

- [ ] **Step 1: Create fixture**

`tests/fixtures/adapters/ingest-drive-pdfs/manifest.yaml`:
```yaml
adapter_name: drive-pdfs
source_name: drive_pdfs
schedule: "0 */6 * * *"
auth:
  type: oauth2
  keychain_service: rufino-drive
output_mode: import_raw
target_inbox: rufino/inbox/
process_with: apunte-clase
trigger: immediate
```

`tests/fixtures/adapters/ingest-drive-pdfs/fetcher.py`:
```python
"""Stub fetcher that returns a list of (filename, content) pairs."""

CANNED = [
    ("clase4-svm.md", "Apunte crudo de SVM."),
    ("clase5-trees.md", "Apunte crudo de decision trees."),
]


def fetch(since: str | None) -> list[dict]:
    return [{"filename": fn, "content": c} for fn, c in CANNED]
```

- [ ] **Step 2: Failing test**

`tests/test_ingest_runner_import_raw.py`:
```python
from pathlib import Path
from unittest.mock import MagicMock
from rufino.engine.ingest.runner import run_ingest


FIXTURE = Path(__file__).parent / "fixtures" / "adapters" / "ingest-drive-pdfs"


def test_import_raw_writes_to_inbox(tmp_vault: Path, tmp_path: Path):
    inbox = tmp_vault / "rufino" / "inbox"
    # Setup process hook so we know if it was invoked
    process_calls = []

    def stub_process_hook(note_path: Path, vault_root: Path, adapter_name: str):
        process_calls.append((note_path, vault_root, adapter_name))

    result = run_ingest(
        adapter_dir=FIXTURE,
        vault_root=tmp_vault,
        rufino_state_dir=tmp_path / ".rufino-state",
        process_hook=stub_process_hook,
    )

    assert (inbox / "clase4-svm.md").exists()
    assert (inbox / "clase5-trees.md").exists()
    # Trigger immediate → Process should have been invoked twice
    assert len(process_calls) == 2
    assert all(c[2] == "apunte-clase" for c in process_calls)


def test_import_raw_defer_skips_process_call(tmp_vault: Path, tmp_path: Path):
    fixture_defer = tmp_path / "defer-adapter"
    fixture_defer.mkdir()
    (fixture_defer / "manifest.yaml").write_text(
        "adapter_name: defer\nsource_name: defer\nschedule: '0 0 * * *'\n"
        "auth: {}\noutput_mode: import_raw\ntarget_inbox: inbox/\n"
        "process_with: x\ntrigger: defer\n"
    )
    (fixture_defer / "fetcher.py").write_text(
        "def fetch(since):\n    return [{'filename':'a.md','content':'x'}]\n"
    )

    process_calls = []
    result = run_ingest(
        adapter_dir=fixture_defer,
        vault_root=tmp_vault,
        rufino_state_dir=tmp_path / ".rufino-state",
        process_hook=lambda *a, **kw: process_calls.append(True),
    )
    assert (tmp_vault / "inbox" / "a.md").exists()
    assert process_calls == []  # defer → no immediate process
```

- [ ] **Step 3: Run (fails)**

- [ ] **Step 4: Implement** — replace the `NotImplementedError` body of `_run_import_raw`

In `src/rufino/engine/ingest/runner.py`:

```python
def run_ingest(
    *,
    adapter_dir: Path,
    vault_root: Path,
    rufino_state_dir: Path,
    process_hook=None,    # callable(note_path, vault_root, adapter_name) | None
) -> IngestResult:
    manifest = parse_ingest_manifest((adapter_dir / "manifest.yaml").read_text())
    if manifest.output_mode == "emit_fact":
        return _run_emit_fact(
            adapter_dir=adapter_dir, manifest=manifest,
            vault_root=vault_root, rufino_state_dir=rufino_state_dir,
        )
    if manifest.output_mode == "import_raw":
        return _run_import_raw(
            adapter_dir=adapter_dir, manifest=manifest,
            vault_root=vault_root, rufino_state_dir=rufino_state_dir,
            process_hook=process_hook,
        )
    raise NotImplementedError(f"output_mode {manifest.output_mode} not implemented")


def _run_import_raw(
    *, adapter_dir, manifest, vault_root: Path, rufino_state_dir: Path, process_hook,
) -> IngestResult:
    fetcher = load_fetcher(adapter_dir)
    cursors = CursorStore(rufino_state_dir / "cursors.json")

    since = cursors.get(manifest.adapter_name)
    items = fetcher(since=since)

    inbox = vault_root / manifest.target_inbox
    inbox.mkdir(parents=True, exist_ok=True)
    emitted = 0

    for item in items:
        target = inbox / item["filename"]
        target.write_text(item["content"])
        emitted += 1
        if manifest.trigger == "immediate" and process_hook is not None:
            process_hook(target, vault_root, manifest.process_with)

    cursors.set(manifest.adapter_name, datetime.utcnow().isoformat() + "Z")
    return IngestResult(
        adapter_name=manifest.adapter_name,
        facts_emitted=emitted,
        facts_skipped=0,
        errors=[],
    )
```

- [ ] **Step 5: Run tests** — Expected: 2 passed (plus earlier emit_fact tests)

- [ ] **Step 6: Commit**

```bash
git add src/rufino/engine/ingest/runner.py tests/fixtures/adapters/ingest-drive-pdfs/ tests/test_ingest_runner_import_raw.py
git commit -m "feat(ingest): runner import_raw mode with optional push to Process"
```

---

## Task 8: CLI command `rufino ingest <adapter_dir>`

**Files:**
- Modify: `src/rufino/cli.py`
- Create: `tests/test_cli_ingest.py`

- [ ] **Step 1: Failing test**

`tests/test_cli_ingest.py`:
```python
from pathlib import Path
from click.testing import CliRunner
from rufino.cli import cli


FIXTURE = Path(__file__).parent / "fixtures" / "adapters" / "ingest-belo"


def test_ingest_cli_emits_facts(tmp_vault: Path, tmp_path: Path):
    runner = CliRunner()
    result = runner.invoke(cli, [
        "ingest", str(FIXTURE),
        "--vault", str(tmp_vault),
        "--state-dir", str(tmp_path / ".rufino-state"),
    ])
    assert result.exit_code == 0, result.output
    assert "emitted=2" in result.output
```

- [ ] **Step 2: Run (fails)**

- [ ] **Step 3: Append to `src/rufino/cli.py`**

```python
from rufino.engine.ingest.runner import run_ingest


@cli.command(name="ingest")
@click.argument("adapter_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--vault", "vault_root", required=True, type=click.Path(path_type=Path))
@click.option("--state-dir", "state_dir", required=True, type=click.Path(path_type=Path))
def ingest_cmd(adapter_dir: Path, vault_root: Path, state_dir: Path) -> None:
    """Run an Ingest adapter once."""
    result = run_ingest(
        adapter_dir=adapter_dir,
        vault_root=vault_root,
        rufino_state_dir=state_dir,
    )
    click.echo(
        f"adapter={result.adapter_name} emitted={result.facts_emitted} "
        f"skipped={result.facts_skipped} errors={len(result.errors)}"
    )
```

- [ ] **Step 4: Run tests** — Expected: 1 passed

- [ ] **Step 5: Run full suite**

Run: `pytest -v`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add src/rufino/cli.py tests/test_cli_ingest.py
git commit -m "feat(ingest): CLI command 'rufino ingest'"
```

---

## Self-review checklist

- [ ] Manifest parser rejects mode-specific missing fields (e.g., emit_fact without dedup_by)
- [ ] Cursor persists across `CursorStore` instances
- [ ] Dedup is per-source (different sources can have same fact_id)
- [ ] Fact schema enforces type + enum
- [ ] Fetcher loader handles missing fetcher.py with FileNotFoundError
- [ ] emit_fact: rerun deduplicates correctly
- [ ] import_raw immediate: process_hook called once per imported file
- [ ] import_raw defer: process_hook NOT called

## Done criteria

- `pytest tests/test_ingest_*.py -v` all pass
- `./cli/rufino ingest tests/fixtures/adapters/ingest-belo --vault X --state-dir Y` prints `emitted=2`
- Rerunning the same command prints `emitted=0 skipped=2`
- emit_augmented mode raises `NotImplementedError` (deferred to v1.1)
