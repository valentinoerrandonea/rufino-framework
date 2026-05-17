# Plan 6 — Q&A loop primitive Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementar la primitive Q&A loop: el shape "question template" (markdown puro con frontmatter), la API `ask_user(template_name, context, options)`, el worker que polls `questions/` para detectar answers, y el mecanismo de callback que resume al adapter caller cuando el user contestó.

**Architecture:** `ask_user(...)` crea `questions/<YYYY-MM-DD>-<slug>.md` renderizado desde un template + escribe un callback record en `~/.rufino/state/pending_callbacks.json` con el adapter caller + estado a recuperar. Un worker (invocable via CLI `rufino qa-poll` y schedulable) escanea `questions/` buscando frontmatter con `answer:` lleno, ejecuta el callback registrado, mueve la question a `questions/answered/`.

**Tech Stack:** Python 3.11+, pyyaml, jinja2 (template rendering).

**Dependencias previas:** Plan 1 (Foundation), Plan 5 (jinja2 ya disponible).

**Plans que dependen de este:** Plan 3 (Process — reemplaza StubQALoop con la implementación real), Plan 8 (Wizard).

---

## File Structure

```
src/rufino/engine/qa/
├── __init__.py
├── template.py             # parse template + render
├── store.py                # write question file, list pending, mark answered
├── api.py                  # ask_user(...), get_answer(...), on_answer(...)
├── worker.py               # poll loop: detect answers, dispatch callbacks
└── callback_registry.py    # serialize callbacks (adapter name + state) to disk
src/rufino/cli.py           # MODIFY: `rufino qa-poll`
tests/test_qa_*.py
tests/fixtures/qa-templates/
└── materia-ambigua.md
```

---

## Task 1: Template parsing + rendering

**Files:**
- Create: `src/rufino/engine/qa/__init__.py`
- Create: `src/rufino/engine/qa/template.py`
- Create: `tests/fixtures/qa-templates/materia-ambigua.md`
- Create: `tests/test_qa_template.py`

- [ ] **Step 1: Create fixture template**

`tests/fixtures/qa-templates/materia-ambigua.md`:
```markdown
---
template_name: materia_ambigua
required_context: [apunte_slug, candidate_materias, evidence]
expected_answer: "enum_from(candidate_materias) | 'nueva' | 'ninguna'"
---

# ¿De qué materia es {{ apunte_slug }}?

Encontré candidatos:
{% for c in candidate_materias -%}
- **[[materia-{{ c.slug }}]]** ({{ c.confidence }}% — {{ c.reason }})
{% endfor %}

## Evidencia
{{ evidence }}

## Respondé editando frontmatter
`answer: <slug>` | `answer: nueva` + `nueva_materia: <slug>` | `answer: ninguna`
```

- [ ] **Step 2: Failing test**

`tests/test_qa_template.py`:
```python
import pytest
from pathlib import Path
from rufino.engine.qa.template import (
    QuestionTemplate,
    parse_template_file,
    render_question,
    TemplateError,
)


FIXTURE = Path(__file__).parent / "fixtures" / "qa-templates" / "materia-ambigua.md"


def test_parses_template_metadata():
    t = parse_template_file(FIXTURE)
    assert t.template_name == "materia_ambigua"
    assert "apunte_slug" in t.required_context
    assert "enum_from" in t.expected_answer


def test_renders_with_full_context():
    t = parse_template_file(FIXTURE)
    rendered = render_question(t, context={
        "apunte_slug": "clase3",
        "candidate_materias": [
            {"slug": "ml-i", "confidence": 70, "reason": "menciona regresión"},
            {"slug": "stats-ii", "confidence": 60, "reason": "menciona inferencia"},
        ],
        "evidence": "fragmento del texto",
    })
    assert "clase3" in rendered
    assert "[[materia-ml-i]]" in rendered
    assert "70%" in rendered
    assert "fragmento del texto" in rendered


def test_render_with_missing_required_context_raises():
    t = parse_template_file(FIXTURE)
    with pytest.raises(TemplateError, match="apunte_slug"):
        render_question(t, context={})
```

- [ ] **Step 3: Run (fails)**

- [ ] **Step 4: Implement**

`src/rufino/engine/qa/__init__.py`: `` (empty)

`src/rufino/engine/qa/template.py`:
```python
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import yaml
from jinja2 import Environment, BaseLoader, StrictUndefined


class TemplateError(Exception):
    """Raised when template parsing or rendering fails."""


@dataclass(frozen=True)
class QuestionTemplate:
    template_name: str
    required_context: tuple[str, ...]
    expected_answer: str
    body_template: str  # markdown after the frontmatter


_ENV = Environment(loader=BaseLoader(), undefined=StrictUndefined, autoescape=False)


def parse_template_file(path: Path) -> QuestionTemplate:
    text = path.read_text()
    if not text.startswith("---\n"):
        raise TemplateError(f"Template {path} missing frontmatter")
    try:
        _, fm_block, body = text.split("---\n", 2)
    except ValueError:
        raise TemplateError(f"Template {path} unterminated frontmatter")

    fm = yaml.safe_load(fm_block) or {}
    for required in ("template_name", "required_context", "expected_answer"):
        if required not in fm:
            raise TemplateError(f"Template {path} missing frontmatter field: {required}")

    return QuestionTemplate(
        template_name=fm["template_name"],
        required_context=tuple(fm["required_context"]),
        expected_answer=fm["expected_answer"],
        body_template=body,
    )


def render_question(template: QuestionTemplate, *, context: dict[str, Any]) -> str:
    missing = [c for c in template.required_context if c not in context]
    if missing:
        raise TemplateError(f"Missing required context: {missing}")
    tmpl = _ENV.from_string(template.body_template)
    return tmpl.render(**context)
```

- [ ] **Step 5: Run tests** — Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
git add src/rufino/engine/qa/__init__.py src/rufino/engine/qa/template.py tests/fixtures/qa-templates/ tests/test_qa_template.py
git commit -m "feat(qa): template parsing + jinja2 rendering"
```

---

## Task 2: Question store (write + list pending + mark answered)

**Files:**
- Create: `src/rufino/engine/qa/store.py`
- Create: `tests/test_qa_store.py`

- [ ] **Step 1: Failing test**

`tests/test_qa_store.py`:
```python
from pathlib import Path
from rufino.engine.qa.store import (
    QuestionStore,
    Question,
)


def test_write_creates_question_file(tmp_vault: Path):
    qdir = tmp_vault / "questions"
    qdir.mkdir()
    store = QuestionStore(qdir)

    q_id = store.write_question(
        slug="2026-05-16-materia-clase3",
        template_name="materia_ambigua",
        body="¿De qué materia es clase3?",
    )

    q_file = qdir / "2026-05-16-materia-clase3.md"
    assert q_file.exists()
    assert "materia_ambigua" in q_file.read_text()
    assert "answer:" in q_file.read_text()


def test_list_pending_returns_unanswered(tmp_vault: Path):
    qdir = tmp_vault / "questions"
    qdir.mkdir()
    store = QuestionStore(qdir)

    store.write_question(slug="q1", template_name="t", body="b1")
    store.write_question(slug="q2", template_name="t", body="b2")

    # Answer q1
    (qdir / "q1.md").write_text(
        (qdir / "q1.md").read_text().replace("answer:", "answer: ml-i")
    )

    pending = store.list_pending()
    pending_slugs = [q.slug for q in pending]
    assert "q1" not in pending_slugs
    assert "q2" in pending_slugs


def test_get_answer_returns_string(tmp_vault: Path):
    qdir = tmp_vault / "questions"
    qdir.mkdir()
    store = QuestionStore(qdir)
    store.write_question(slug="q1", template_name="t", body="b")
    (qdir / "q1.md").write_text(
        (qdir / "q1.md").read_text().replace("answer:", "answer: ml-i")
    )
    assert store.get_answer("q1") == "ml-i"


def test_get_answer_returns_none_when_unanswered(tmp_vault: Path):
    qdir = tmp_vault / "questions"
    qdir.mkdir()
    store = QuestionStore(qdir)
    store.write_question(slug="q1", template_name="t", body="b")
    assert store.get_answer("q1") is None


def test_mark_answered_moves_file(tmp_vault: Path):
    qdir = tmp_vault / "questions"
    qdir.mkdir()
    store = QuestionStore(qdir)
    store.write_question(slug="q1", template_name="t", body="b")

    store.mark_answered("q1")

    assert not (qdir / "q1.md").exists()
    assert (qdir / "answered" / "q1.md").exists()
```

- [ ] **Step 2: Run (fails)**

- [ ] **Step 3: Implement**

`src/rufino/engine/qa/store.py`:
```python
from dataclasses import dataclass
from pathlib import Path
import yaml


@dataclass(frozen=True)
class Question:
    slug: str
    template_name: str
    answer: str | None
    path: Path


class QuestionStore:
    """Read/write question files in the vault's questions/ directory."""

    def __init__(self, questions_dir: Path) -> None:
        self._dir = questions_dir
        (questions_dir / "answered").mkdir(exist_ok=True)

    def write_question(self, *, slug: str, template_name: str, body: str) -> str:
        path = self._dir / f"{slug}.md"
        path.write_text(
            "---\n"
            f"template_name: {template_name}\n"
            f"answer:\n"
            "---\n"
            f"{body}\n"
        )
        return slug

    def get_answer(self, slug: str) -> str | None:
        path = self._dir / f"{slug}.md"
        if not path.exists():
            # Maybe already answered and moved
            answered = self._dir / "answered" / f"{slug}.md"
            if answered.exists():
                return self._read_answer(answered)
            return None
        return self._read_answer(path)

    def list_pending(self) -> list[Question]:
        out: list[Question] = []
        for p in self._dir.glob("*.md"):
            if not p.is_file():
                continue
            fm = self._read_frontmatter(p)
            answer = fm.get("answer")
            if answer is None or (isinstance(answer, str) and answer.strip() == ""):
                out.append(Question(
                    slug=p.stem,
                    template_name=fm.get("template_name", "unknown"),
                    answer=None,
                    path=p,
                ))
        return out

    def mark_answered(self, slug: str) -> None:
        src = self._dir / f"{slug}.md"
        dst = self._dir / "answered" / f"{slug}.md"
        src.rename(dst)

    def _read_answer(self, path: Path) -> str | None:
        fm = self._read_frontmatter(path)
        ans = fm.get("answer")
        if ans is None:
            return None
        if isinstance(ans, str) and ans.strip() == "":
            return None
        return str(ans)

    def _read_frontmatter(self, path: Path) -> dict:
        text = path.read_text()
        if not text.startswith("---\n"):
            return {}
        _, block, _ = text.split("---\n", 2)
        return yaml.safe_load(block) or {}
```

- [ ] **Step 4: Run tests** — Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/rufino/engine/qa/store.py tests/test_qa_store.py
git commit -m "feat(qa): QuestionStore for write/list/mark-answered"
```

---

## Task 3: Callback registry

**Files:**
- Create: `src/rufino/engine/qa/callback_registry.py`
- Create: `tests/test_qa_callback_registry.py`

- [ ] **Step 1: Failing test**

`tests/test_qa_callback_registry.py`:
```python
from pathlib import Path
from rufino.engine.qa.callback_registry import (
    CallbackRegistry,
    PendingCallback,
)


def test_register_and_retrieve(tmp_path: Path):
    reg = CallbackRegistry(tmp_path / "callbacks.json")
    reg.register(PendingCallback(
        question_slug="q1",
        adapter_name="process-apunte-clase",
        adapter_state={"note_path": "/tmp/n.md"},
    ))

    cb = reg.get("q1")
    assert cb is not None
    assert cb.adapter_name == "process-apunte-clase"
    assert cb.adapter_state["note_path"] == "/tmp/n.md"


def test_persists_across_instances(tmp_path: Path):
    p = tmp_path / "callbacks.json"
    CallbackRegistry(p).register(PendingCallback(
        question_slug="q1", adapter_name="x", adapter_state={},
    ))
    assert CallbackRegistry(p).get("q1") is not None


def test_consume_removes_callback(tmp_path: Path):
    reg = CallbackRegistry(tmp_path / "callbacks.json")
    reg.register(PendingCallback(question_slug="q1", adapter_name="x", adapter_state={}))
    cb = reg.consume("q1")
    assert cb is not None
    assert reg.get("q1") is None  # gone after consume
```

- [ ] **Step 2: Run (fails)**

- [ ] **Step 3: Implement**

`src/rufino/engine/qa/callback_registry.py`:
```python
import json
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass(frozen=True)
class PendingCallback:
    question_slug: str
    adapter_name: str
    adapter_state: dict


class CallbackRegistry:
    """JSON-persisted map of pending Q&A callbacks."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._data: dict[str, dict] = {}
        if path.exists():
            self._data = json.loads(path.read_text())

    def register(self, cb: PendingCallback) -> None:
        self._data[cb.question_slug] = {
            "adapter_name": cb.adapter_name,
            "adapter_state": cb.adapter_state,
        }
        self._flush()

    def get(self, slug: str) -> PendingCallback | None:
        raw = self._data.get(slug)
        if raw is None:
            return None
        return PendingCallback(
            question_slug=slug,
            adapter_name=raw["adapter_name"],
            adapter_state=raw["adapter_state"],
        )

    def consume(self, slug: str) -> PendingCallback | None:
        cb = self.get(slug)
        if cb is not None:
            self._data.pop(slug, None)
            self._flush()
        return cb

    def _flush(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, indent=2))
```

- [ ] **Step 4: Run tests** — Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/rufino/engine/qa/callback_registry.py tests/test_qa_callback_registry.py
git commit -m "feat(qa): callback registry persisted to disk"
```

---

## Task 4: Public API — ask_user + get_answer + on_answer

**Files:**
- Create: `src/rufino/engine/qa/api.py`
- Create: `tests/test_qa_api.py`

- [ ] **Step 1: Failing test**

`tests/test_qa_api.py`:
```python
from pathlib import Path
from rufino.engine.qa.api import QALoopAPI


FIXTURE_TEMPLATES = Path(__file__).parent / "fixtures" / "qa-templates"


def test_ask_user_creates_question(tmp_vault: Path, tmp_path: Path):
    api = QALoopAPI(
        vault_root=tmp_vault,
        templates_dir=FIXTURE_TEMPLATES,
        state_dir=tmp_path / ".rufino-state",
    )
    (tmp_vault / "questions").mkdir()

    q_id = api.ask_user(
        template_name="materia_ambigua",
        context={
            "apunte_slug": "clase3",
            "candidate_materias": [{"slug": "ml-i", "confidence": 70, "reason": "r"}],
            "evidence": "e",
        },
        adapter_name="process-apunte-clase",
        adapter_state={"note_path": "/tmp/n.md"},
    )

    assert q_id.startswith("materia_ambigua-")
    q_file = tmp_vault / "questions" / f"{q_id}.md"
    assert q_file.exists()
    assert "clase3" in q_file.read_text()


def test_get_answer_returns_none_when_pending(tmp_vault: Path, tmp_path: Path):
    api = QALoopAPI(
        vault_root=tmp_vault,
        templates_dir=FIXTURE_TEMPLATES,
        state_dir=tmp_path / ".rufino-state",
    )
    (tmp_vault / "questions").mkdir()

    q_id = api.ask_user(
        template_name="materia_ambigua",
        context={
            "apunte_slug": "x",
            "candidate_materias": [{"slug": "a", "confidence": 50, "reason": "r"}],
            "evidence": "e",
        },
        adapter_name="adapter-x",
        adapter_state={},
    )
    assert api.get_answer(q_id) is None
```

- [ ] **Step 2: Run (fails)**

- [ ] **Step 3: Implement**

`src/rufino/engine/qa/api.py`:
```python
import uuid
from dataclasses import dataclass
from pathlib import Path

from rufino.engine.qa.template import parse_template_file, render_question
from rufino.engine.qa.store import QuestionStore
from rufino.engine.qa.callback_registry import CallbackRegistry, PendingCallback


@dataclass
class QALoopAPI:
    vault_root: Path
    templates_dir: Path
    state_dir: Path

    def __post_init__(self) -> None:
        self._store = QuestionStore(self.vault_root / "questions")
        self._registry = CallbackRegistry(self.state_dir / "callbacks.json")

    def ask_user(
        self,
        *,
        template_name: str,
        context: dict,
        adapter_name: str,
        adapter_state: dict,
    ) -> str:
        """Render a question to the vault and register a pending callback.

        Returns the question slug.
        """
        template_path = self.templates_dir / f"{template_name.replace('_', '-')}.md"
        template = parse_template_file(template_path)

        body = render_question(template, context=context)
        slug = f"{template.template_name}-{uuid.uuid4().hex[:8]}"
        self._store.write_question(
            slug=slug,
            template_name=template.template_name,
            body=body,
        )
        self._registry.register(PendingCallback(
            question_slug=slug,
            adapter_name=adapter_name,
            adapter_state=adapter_state,
        ))
        return slug

    def get_answer(self, slug: str) -> str | None:
        return self._store.get_answer(slug)
```

- [ ] **Step 4: Run tests** — Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/rufino/engine/qa/api.py tests/test_qa_api.py
git commit -m "feat(qa): QALoopAPI with ask_user + get_answer"
```

---

## Task 5: Worker — poll, detect answers, dispatch callbacks

**Files:**
- Create: `src/rufino/engine/qa/worker.py`
- Create: `tests/test_qa_worker.py`

- [ ] **Step 1: Failing test**

`tests/test_qa_worker.py`:
```python
from pathlib import Path
from rufino.engine.qa.api import QALoopAPI
from rufino.engine.qa.worker import poll_and_dispatch


FIXTURE_TEMPLATES = Path(__file__).parent / "fixtures" / "qa-templates"


def test_worker_dispatches_callback_when_answer_present(tmp_vault: Path, tmp_path: Path):
    state = tmp_path / ".rufino-state"
    (tmp_vault / "questions").mkdir()
    api = QALoopAPI(
        vault_root=tmp_vault,
        templates_dir=FIXTURE_TEMPLATES,
        state_dir=state,
    )

    q_id = api.ask_user(
        template_name="materia_ambigua",
        context={"apunte_slug": "c", "candidate_materias": [{"slug": "ml-i", "confidence": 70, "reason": "r"}], "evidence": "e"},
        adapter_name="proc-x",
        adapter_state={"note_path": "/tmp/n.md"},
    )

    # User answers
    qf = tmp_vault / "questions" / f"{q_id}.md"
    qf.write_text(qf.read_text().replace("answer:", "answer: ml-i"))

    received: list = []
    def handler(*, adapter_name, adapter_state, answer):
        received.append((adapter_name, adapter_state, answer))

    poll_and_dispatch(
        vault_root=tmp_vault,
        state_dir=state,
        handler=handler,
    )

    assert len(received) == 1
    assert received[0][0] == "proc-x"
    assert received[0][2] == "ml-i"
    # Question moved to answered/
    assert (tmp_vault / "questions" / "answered" / f"{q_id}.md").exists()


def test_worker_skips_pending_questions(tmp_vault: Path, tmp_path: Path):
    state = tmp_path / ".rufino-state"
    (tmp_vault / "questions").mkdir()
    api = QALoopAPI(
        vault_root=tmp_vault,
        templates_dir=FIXTURE_TEMPLATES,
        state_dir=state,
    )
    api.ask_user(
        template_name="materia_ambigua",
        context={"apunte_slug": "c", "candidate_materias": [{"slug": "ml-i", "confidence": 70, "reason": "r"}], "evidence": "e"},
        adapter_name="proc-x",
        adapter_state={},
    )

    received: list = []
    poll_and_dispatch(
        vault_root=tmp_vault,
        state_dir=state,
        handler=lambda **kw: received.append(kw),
    )
    assert received == []  # nothing dispatched
```

- [ ] **Step 2: Run (fails)**

- [ ] **Step 3: Implement**

`src/rufino/engine/qa/worker.py`:
```python
from pathlib import Path
from typing import Callable

from rufino.engine.qa.store import QuestionStore
from rufino.engine.qa.callback_registry import CallbackRegistry


def poll_and_dispatch(
    *,
    vault_root: Path,
    state_dir: Path,
    handler: Callable,
) -> int:
    """For every question with answer present, invoke handler() and mark answered.

    Returns the number of callbacks dispatched.
    """
    store = QuestionStore(vault_root / "questions")
    registry = CallbackRegistry(state_dir / "callbacks.json")
    dispatched = 0

    for q in store.list_pending():  # pending = no answer yet, so skip
        pass

    # Walk all questions/*.md (not just pending) — answer might just have been filled
    for p in (vault_root / "questions").glob("*.md"):
        if not p.is_file():
            continue
        slug = p.stem
        answer = store.get_answer(slug)
        if answer is None:
            continue

        cb = registry.consume(slug)
        if cb is None:
            # Question file exists with answer but no callback was registered for it
            continue

        handler(
            adapter_name=cb.adapter_name,
            adapter_state=cb.adapter_state,
            answer=answer,
        )
        store.mark_answered(slug)
        dispatched += 1

    return dispatched
```

- [ ] **Step 4: Run tests** — Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/rufino/engine/qa/worker.py tests/test_qa_worker.py
git commit -m "feat(qa): worker poll_and_dispatch resumes adapter callbacks"
```

---

## Task 6: CLI command `rufino qa-poll`

**Files:**
- Modify: `src/rufino/cli.py`
- Create: `tests/test_cli_qa_poll.py`

- [ ] **Step 1: Failing test**

`tests/test_cli_qa_poll.py`:
```python
from pathlib import Path
from click.testing import CliRunner
from rufino.cli import cli


def test_qa_poll_cli_runs_with_no_pending(tmp_vault: Path, tmp_path: Path):
    (tmp_vault / "questions").mkdir()
    runner = CliRunner()
    result = runner.invoke(cli, [
        "qa-poll",
        "--vault", str(tmp_vault),
        "--state-dir", str(tmp_path / ".rufino-state"),
    ])
    assert result.exit_code == 0
    assert "dispatched=0" in result.output
```

- [ ] **Step 2: Run (fails)**

- [ ] **Step 3: Append to `src/rufino/cli.py`**

```python
from rufino.engine.qa.worker import poll_and_dispatch


@cli.command(name="qa-poll")
@click.option("--vault", "vault_root", required=True, type=click.Path(path_type=Path))
@click.option("--state-dir", "state_dir", required=True, type=click.Path(path_type=Path))
def qa_poll_cmd(vault_root: Path, state_dir: Path) -> None:
    """Poll questions/ for answered questions and dispatch their callbacks.

    In v1, the handler is a no-op placeholder. Real Process adapter resumption
    lands in plan 8 (Wizard wires QALoopAPI into the Process dispatcher).
    """
    def _noop_handler(*, adapter_name, adapter_state, answer):
        click.echo(f"would resume {adapter_name} with answer={answer!r}")

    dispatched = poll_and_dispatch(
        vault_root=vault_root,
        state_dir=state_dir,
        handler=_noop_handler,
    )
    click.echo(f"dispatched={dispatched}")
```

- [ ] **Step 4: Run tests** — Expected: 1 passed

- [ ] **Step 5: Run full suite**

Run: `pytest -v` — all pass

- [ ] **Step 6: Commit**

```bash
git add src/rufino/cli.py tests/test_cli_qa_poll.py
git commit -m "feat(qa): CLI command 'rufino qa-poll'"
```

---

## Self-review checklist

- [ ] Template renderer raises on missing required_context fields
- [ ] QuestionStore correctly distinguishes empty `answer:` from non-empty
- [ ] CallbackRegistry persists across instances
- [ ] `consume()` removes the entry (idempotency: subsequent calls return None)
- [ ] Worker only dispatches callbacks for questions WITH answers
- [ ] Worker moves answered questions to `questions/answered/`
- [ ] CLI exits 0 when there are no pending questions

## Done criteria

- `pytest tests/test_qa_*.py -v` all pass
- `./cli/rufino qa-poll --vault X --state-dir Y` exits 0 and prints `dispatched=N`
- End-to-end: ask → write answer → poll → callback invoked → question moved
