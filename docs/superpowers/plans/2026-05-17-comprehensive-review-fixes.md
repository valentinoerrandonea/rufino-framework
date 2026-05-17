# Comprehensive Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close all 10 Critical and 10 high-leverage Important findings from the 2026-05-17 comprehensive code review, plus 5 additional Codex findings, so the framework reaches a stable v0.1.

**Architecture:** Six phases ordered by dependency. Phase 1 fixes the load-bearing transaction-log abstraction first because subsequent rollback-related fixes depend on it. Phase 2 closes security holes (path traversal, prompt injection, SSRF, XML injection). Phase 3 closes data-integrity bugs. Phase 4 fixes user-visible correctness (silent garbage, version drift, install/upgrade safety). Phase 5 hardens the remaining Important issues. Phase 6 closes additional CLI/materializer/sandbox inconsistencies found by Codex. Each task is TDD: write failing test → verify failure → implement → verify pass → commit.

**Tech Stack:** Python 3.14 + pytest, click, jinja2, sqlite3, keyring, MCP SDK. Bash for install/upgrade scripts.

**Prerequisite (env, not code):** before starting, ensure the active venv has all dev deps. Run from repo root:
```bash
pip install -e ".[dev]"
pytest -q  # must collect without ModuleNotFoundError
```

---

## Codex Review Addendum — 2026-05-17

**Assessment of Claude's review:** mostly accurate in direction and severity. The plan identifies real classes of bugs in transaction rollback, output/webhook hardening, scheduler XML escaping, misleading semantic search, install/update drift, and MCP schema hardening. Several tasks need API-level adjustment before implementation because some proposed tests reference names or constructor arguments that do not exist in the current codebase.

**Concrete corrections before implementation:**

- Task 7's test uses `ScheduledJob(..., interval_seconds=60)`, but `ScheduledJob` currently requires `cron`, not `interval_seconds`. Keep the XML escaping finding, but write the test with `cron="0 22 * * *"`.
- Task 8's proposed test imports `Callback` and calls `QuestionStore.write_question(slug=..., question=...)` / `write_answer()`, but the current APIs are `PendingCallback`, `write_question(slug, template_name, body)`, and direct answer editing in the markdown frontmatter. The atomicity finding is still valid, but the test needs to use current APIs.
- Task 9 repeats the same `QuestionStore.write_question(..., question=...)` mismatch. Use `template_name` and `body`.
- Task 12 correctly flags `_NoopEmbeddings`, but Step 3 is internally inconsistent: if `_NoopEmbeddings.embed()` raises, then `query --mode hybrid` cannot merely warn and continue. Prefer making `semantic` and `hybrid` exit non-zero until a real embedder is wired, or make CLI default to `lexical`.
- Task 15 improves stale MCP registration when `RUFINO_VAULT` is set, but it does not close the full bootstrap gap: README/install comments say bootstrap/materialize will register MCP after vault creation, yet neither command currently does.
- Task 20 references `SpecValidationError`, but the current exception class is `SpecError`. It also omits the required `patterns` field from its example specs.

**Additional findings from Codex review:**

- `rufino qa-poll` currently consumes answered questions with a no-op handler, deleting the pending callback and archiving the question without resuming any adapter.
- `materialize()` creates an incomplete vault skeleton: no `inbox/`, no `_meta/_tags.md`, no `_meta/_processing-log.md`, despite generated docs and `process light` depending on them.
- `rufino output` always uses `StubQueryLayer()`, so real output adapters render with empty query results even when the vault contains matching notes.
- MCP registration is still not performed after a vault is materialized unless the user pre-sets `RUFINO_VAULT` before install.
- `run_transform_hook(..., allow_network=False)` does not actually enforce the flag; Python hooks can still use stdlib networking.

These are tracked as Phase 6 tasks below. They should be implemented after Phase 4 Task 15, because several depend on the same CLI/materializer distribution surface.

---

## Phase 1 — Foundation (transaction log + version sync)

### Task 1: Register missing rollback handlers in transaction_log.py

**Why this is first:** Without these handlers a partial-bootstrap rollback raises `RuntimeError("No rollback handler registered for 'keychain_delete'")` exactly when the framework most needs to clean up. This is the highest-severity Critical in the review.

**Files:**
- Modify: `src/rufino/runtime/transaction_log.py`
- Test: `tests/test_transaction_log.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_transaction_log.py`:

```python
def test_record_rejects_unknown_rollback_name(tmp_path):
    log = TransactionLog(tmp_path / "log.json")
    with pytest.raises(ValueError, match="unknown rollback"):
        log.record(LogEntry(op="custom", target="x", rollback="not_a_real_handler"))


def test_rmdir_if_empty_handler_removes_empty_dir(tmp_path):
    target = tmp_path / "empty"
    target.mkdir()
    log = TransactionLog(tmp_path / "log.json")
    log.record(LogEntry(op="mkdir", target=str(target), rollback="rmdir_if_empty"))
    log.rollback()
    assert not target.exists()


def test_rmdir_if_empty_handler_preserves_nonempty_dir(tmp_path):
    target = tmp_path / "with_content"
    target.mkdir()
    (target / "user_file.txt").write_text("foreign")
    log = TransactionLog(tmp_path / "log.json")
    log.record(LogEntry(op="mkdir", target=str(target), rollback="rmdir_if_empty"))
    log.rollback()
    assert target.exists()
    assert (target / "user_file.txt").read_text() == "foreign"


def test_keychain_delete_and_plist_uninstall_handlers_are_registered():
    from rufino.runtime.transaction_log import _ROLLBACK_REGISTRY
    assert "keychain_delete" in _ROLLBACK_REGISTRY
    assert "plist_uninstall" in _ROLLBACK_REGISTRY
    assert "rmdir_if_empty" in _ROLLBACK_REGISTRY
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_transaction_log.py -k "rmdir_if_empty or unknown_rollback or keychain_delete_and" -v
```
Expected: 4 FAILED (handler not registered / no check at record time).

- [ ] **Step 3: Implement the handlers + record-time check**

Replace lines 27-40 of `src/rufino/runtime/transaction_log.py`:

```python
def _rmdir(target: str) -> None:
    p = Path(target)
    if p.exists():
        shutil.rmtree(p) if p.is_dir() else p.unlink()


def _delete(target: str) -> None:
    p = Path(target)
    if p.exists():
        p.unlink()


def _rmdir_if_empty(target: str) -> None:
    p = Path(target)
    if p.exists() and p.is_dir() and not any(p.iterdir()):
        p.rmdir()


def _keychain_delete(target: str) -> None:
    """Delete a keychain entry. target encodes 'service\x00account'."""
    try:
        import keyring
    except ImportError:
        return
    if "\x00" not in target:
        return
    service, account = target.split("\x00", 1)
    try:
        keyring.delete_password(service, account)
    except Exception:
        pass


def _plist_uninstall(target: str) -> None:
    """Unload + remove a launchd plist. target is the absolute plist path."""
    import subprocess
    p = Path(target)
    if p.exists():
        subprocess.run(["launchctl", "unload", str(p)], check=False)
        p.unlink()


register_rollback("rmdir", _rmdir)
register_rollback("delete", _delete)
register_rollback("rmdir_if_empty", _rmdir_if_empty)
register_rollback("keychain_delete", _keychain_delete)
register_rollback("plist_uninstall", _plist_uninstall)
```

Then modify `TransactionLog.record` (line 50-52):

```python
    def record(self, entry: LogEntry) -> None:
        if entry.rollback not in _ROLLBACK_REGISTRY:
            raise ValueError(
                f"unknown rollback handler {entry.rollback!r}; "
                f"call register_rollback() first"
            )
        self._entries.append(entry)
        self._flush()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_transaction_log.py -v
```
Expected: all PASS, including the 4 new ones.

- [ ] **Step 5: Commit**

```bash
git add src/rufino/runtime/transaction_log.py tests/test_transaction_log.py
git commit -m "fix(runtime): register missing rollback handlers + fail-fast on unknown"
```

---

### Task 2: Make register_rollback thread-safe and add fsync to _flush

**Files:**
- Modify: `src/rufino/runtime/transaction_log.py`
- Test: `tests/test_transaction_log.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_transaction_log.py`:

```python
def test_register_rollback_concurrent_does_not_lose_entries():
    import threading
    from rufino.runtime.transaction_log import register_rollback, _ROLLBACK_REGISTRY

    def make_handler(_name):
        return lambda target: None

    names = [f"concurrent_handler_{i}" for i in range(50)]
    threads = [
        threading.Thread(target=lambda n=n: register_rollback(n, make_handler(n)))
        for n in names
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    for n in names:
        assert n in _ROLLBACK_REGISTRY


def test_flush_fsyncs_to_disk(tmp_path, monkeypatch):
    fsyncs: list[int] = []
    real_fsync = __import__("os").fsync
    monkeypatch.setattr("os.fsync", lambda fd: (fsyncs.append(fd), real_fsync(fd))[1])
    log = TransactionLog(tmp_path / "log.json")
    log.record(LogEntry(op="mkdir", target=str(tmp_path / "x"), rollback="rmdir"))
    assert len(fsyncs) >= 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_transaction_log.py -k "concurrent or fsync" -v
```
Expected: `fsync` FAIL (no fsync called); `concurrent` may pass flakily.

- [ ] **Step 3: Implement the thread-lock + fsync**

Add at top of `src/rufino/runtime/transaction_log.py`:

```python
import os
import threading
```

Replace the registry block:

```python
_ROLLBACK_REGISTRY: dict[str, Callable[[str], None]] = {}
_REGISTRY_LOCK = threading.Lock()


def register_rollback(name: str, fn: Callable[[str], None]) -> None:
    with _REGISTRY_LOCK:
        _ROLLBACK_REGISTRY[name] = fn
```

Replace `_flush`:

```python
    def _flush(self) -> None:
        """Atomic write: stage to .tmp, fsync, rename, fsync parent dir."""
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        data = json.dumps([e.to_dict() for e in self._entries], indent=2)
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        tmp.replace(self._path)
        dir_fd = os.open(self._path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        except OSError:
            pass
        finally:
            os.close(dir_fd)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_transaction_log.py -v
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/rufino/runtime/transaction_log.py tests/test_transaction_log.py
git commit -m "fix(runtime): thread-safe rollback registry + fsync on flush"
```

---

### Task 3: Add version-sync test (pyproject.toml ↔ version.py)

**Files:**
- Create: `tests/test_version_sync.py`

- [ ] **Step 1: Write the failing test**

```python
import re
from pathlib import Path

from rufino.version import VERSION


def test_pyproject_version_matches_version_py():
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, flags=re.MULTILINE)
    assert m, "no version line in pyproject.toml"
    assert m.group(1) == VERSION, (
        f"pyproject.toml version {m.group(1)!r} != src/rufino/version.py VERSION {VERSION!r}"
    )
```

- [ ] **Step 2: Run test to verify current state**

```bash
pytest tests/test_version_sync.py -v
```
Expected: PASS today (both are `0.0.1`). The test exists so future drift fails CI.

- [ ] **Step 3: Commit**

```bash
git add tests/test_version_sync.py
git commit -m "test: guard against pyproject/version.py drift"
```

---

## Phase 2 — Security fixes

### Task 4: Fix path-traversal in process dispatcher (_resolve_destination returns resolved path)

**Files:**
- Modify: `src/rufino/engine/process/dispatcher.py:78-84`
- Test: `tests/test_process_dispatcher_security.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
def test_resolve_destination_returns_resolved_path(tmp_path):
    from rufino.engine.process.dispatcher import _resolve_destination
    vault = tmp_path / "vault"
    vault.mkdir()
    result = _resolve_destination(vault, "sub/note.md")
    assert result == (vault / "sub/note.md").resolve()


def test_resolve_destination_rejects_traversal_via_resolved_check(tmp_path):
    from rufino.engine.process.dispatcher import (
        _resolve_destination, DestinationOutsideVaultError,
    )
    vault = tmp_path / "vault"
    vault.mkdir()
    with pytest.raises(DestinationOutsideVaultError):
        _resolve_destination(vault, "../escape.md")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_process_dispatcher_security.py -k "resolve_destination" -v
```
Expected: `returns_resolved_path` FAIL (today it returns unresolved `vault_root / dest_rel`).

- [ ] **Step 3: Fix _resolve_destination**

Replace lines 71-84 of `src/rufino/engine/process/dispatcher.py`:

```python
def _resolve_destination(vault_root: Path, dest_rel: str) -> Path:
    """Resolve `dest_rel` under `vault_root`, rejecting any path that escapes."""
    vault_resolved = vault_root.resolve()
    dest = (vault_root / dest_rel).resolve()
    if vault_resolved != dest and vault_resolved not in dest.parents:
        raise DestinationOutsideVaultError(
            f"destination {dest_rel!r} resolves outside vault {vault_root}"
        )
    return dest
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_process_dispatcher_security.py -v
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/rufino/engine/process/dispatcher.py tests/test_process_dispatcher_security.py
git commit -m "fix(process): _resolve_destination returns resolved path (path traversal)"
```

---

### Task 5: Close prompt-injection in process dispatcher by switching to jinja2 strict

**Files:**
- Modify: `src/rufino/engine/process/dispatcher.py:109-111`
- Test: `tests/test_process_dispatcher_security.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
def test_note_body_with_context_placeholder_is_not_substituted(tmp_path, monkeypatch):
    """Body containing {{context.X}} must not consume context fields."""
    from rufino.engine.process.dispatcher import _render_prompt
    template = "Body: {{note_body}} | secret: {{context.api_key}}"
    body = "harmless {{context.api_key}} text"  # injection attempt
    context = {"api_key": "SHOULD_NOT_LEAK_VIA_BODY"}
    rendered = _render_prompt(template=template, body=body, context=context)
    # The body's literal {{context.api_key}} must remain literal, not substituted.
    assert "harmless {{context.api_key}} text" in rendered
    # The template's own placeholder should still substitute.
    assert "SHOULD_NOT_LEAK_VIA_BODY" in rendered
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_process_dispatcher_security.py -k "context_placeholder" -v
```
Expected: FAIL (`_render_prompt` does not exist yet; old code uses `str.replace`).

- [ ] **Step 3: Extract a safe renderer and use it**

Add to `src/rufino/engine/process/dispatcher.py` (after imports):

```python
from jinja2 import Environment, StrictUndefined, BaseLoader

_PROMPT_ENV = Environment(
    loader=BaseLoader(),
    undefined=StrictUndefined,
    autoescape=False,
    keep_trailing_newline=True,
)


def _render_prompt(*, template: str, body: str, context: dict[str, str]) -> str:
    """Render a process prompt template with note_body and context.* fields.

    Uses jinja2 with StrictUndefined so a typo in the template surfaces.
    Crucially, only the *template* string is interpreted as jinja — `body` and
    `context.*` values are passed as variables and are NOT re-rendered, closing
    the injection vector where a note body containing `{{context.X}}` could
    consume context fields under the old `str.replace` implementation.
    """
    tpl = _PROMPT_ENV.from_string(template)
    return tpl.render(note_body=body, context=context)
```

Replace lines 109-111 in `_process_full`:

```python
    rendered = _render_prompt(
        template=prompt_template, body=current_body, context=context,
    )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_process_dispatcher_security.py -v
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/rufino/engine/process/dispatcher.py tests/test_process_dispatcher_security.py
git commit -m "fix(process): use jinja2 StrictUndefined for prompt rendering (injection)"
```

---

### Task 6: SSRF guard in webhook channel

**Files:**
- Modify: `src/rufino/engine/output/channels/webhook_channel.py`
- Test: `tests/test_output_channel_webhook_push.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_output_channel_webhook_push.py`:

```python
import pytest
from rufino.engine.output.channels.webhook_channel import (
    WebhookChannel, InvalidWebhookTargetError,
)


@pytest.mark.parametrize("url", [
    "http://localhost:8080/x",
    "http://127.0.0.1/x",
    "http://10.0.0.1/x",
    "http://192.168.1.1/x",
    "http://172.16.0.1/x",
    "http://169.254.169.254/latest/meta-data",  # AWS metadata
    "http://[::1]/x",
])
def test_webhook_blocks_private_and_loopback(url):
    with pytest.raises(InvalidWebhookTargetError):
        WebhookChannel().deliver(config={"url": url}, content="x")


def test_webhook_blocks_unresolved_localhost_hostname():
    with pytest.raises(InvalidWebhookTargetError):
        WebhookChannel().deliver(config={"url": "http://localhost.localdomain/"}, content="x")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_output_channel_webhook_push.py -k "blocks_" -v
```
Expected: FAIL (`InvalidWebhookTargetError` does not exist; URLs not blocked).

- [ ] **Step 3: Implement the SSRF guard**

Replace `src/rufino/engine/output/channels/webhook_channel.py`:

```python
import ipaddress
import json
import socket
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


class InvalidWebhookSchemeError(Exception):
    """Raised when a webhook URL uses a non-http(s) scheme."""


class InvalidWebhookTargetError(Exception):
    """Raised when a webhook URL resolves to a disallowed host (SSRF guard)."""


_ALLOWED_SCHEMES = {"https", "http"}
_BLOCKED_HOSTNAMES = {"localhost", "localhost.localdomain", "ip6-localhost"}


def _is_blocked_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _assert_safe_target(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise InvalidWebhookSchemeError(
            f"Webhook URL scheme must be http(s), got {parsed.scheme!r}"
        )
    host = (parsed.hostname or "").lower()
    if not host:
        raise InvalidWebhookTargetError("Webhook URL missing hostname")
    if host in _BLOCKED_HOSTNAMES:
        raise InvalidWebhookTargetError(f"Blocked hostname: {host!r}")
    # If the host parses as an IP literal, check directly.
    if _is_blocked_ip(host.strip("[]")):
        raise InvalidWebhookTargetError(f"Blocked IP literal: {host!r}")
    # Resolve DNS and reject if any A/AAAA points into a blocked range.
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise InvalidWebhookTargetError(f"DNS lookup failed for {host!r}: {e}")
    for info in infos:
        ip_str = info[4][0]
        if _is_blocked_ip(ip_str):
            raise InvalidWebhookTargetError(
                f"Host {host!r} resolves to blocked IP {ip_str}"
            )


@dataclass
class WebhookChannel:
    def deliver(self, *, config: dict[str, Any], content: str) -> None:
        url = config["url"]
        _assert_safe_target(url)
        payload = json.dumps({"content": content}).encode("utf-8")
        req = urllib.request.Request(
            url=url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as _resp:  # noqa: S310
            pass
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_output_channel_webhook_push.py -v
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/rufino/engine/output/channels/webhook_channel.py tests/test_output_channel_webhook_push.py
git commit -m "fix(output): SSRF guard on webhook channel (loopback/private/metadata)"
```

---

### Task 7: XML-escape scheduler plist fields

**Files:**
- Modify: `src/rufino/runtime/scheduler.py`
- Test: `tests/test_scheduler.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_scheduler.py`:

```python
import xml.etree.ElementTree as ET


def test_scheduler_escapes_xml_special_chars_in_command():
    from rufino.runtime.scheduler import LaunchdScheduler, ScheduledJob
    job = ScheduledJob(
        name="com.example.test",
        command="echo 'a < b && c > d'",
        interval_seconds=60,
    )
    plist = LaunchdScheduler().render(job)
    root = ET.fromstring(plist)  # must parse cleanly
    assert "a < b && c > d" not in plist  # raw must not appear
    assert "&lt; b &amp;&amp; c &gt;" in plist


def test_scheduler_rejects_bad_name():
    import pytest
    from rufino.runtime.scheduler import ScheduledJob
    with pytest.raises(ValueError):
        ScheduledJob(name="../../etc/passwd", command="x", interval_seconds=60)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_scheduler.py -k "escapes_xml or rejects_bad_name" -v
```
Expected: FAIL.

- [ ] **Step 3: Implement escaping + name regex**

In `src/rufino/runtime/scheduler.py`, add at top:

```python
import re
from xml.sax.saxutils import escape as _xml_escape

_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
```

Modify `ScheduledJob.__post_init__` (add name check next to existing newline check):

```python
        if not _NAME_RE.match(self.name):
            raise ValueError(
                f"ScheduledJob.name must match {_NAME_RE.pattern}, got {self.name!r}"
            )
```

In `LaunchdScheduler.render`, escape `self.name` and `self.command` before interpolation:

```python
        name_xml = _xml_escape(job.name)
        command_xml = _xml_escape(job.command)
        # ... use name_xml/command_xml in the template instead of raw values
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_scheduler.py -v
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/rufino/runtime/scheduler.py tests/test_scheduler.py
git commit -m "fix(runtime): XML-escape scheduler fields + validate plist name"
```

---

## Phase 3 — Data integrity

### Task 8: Q&A worker atomicity (mark_answered before delete)

**Files:**
- Modify: `src/rufino/engine/qa/worker.py:68-70`
- Test: `tests/test_qa_worker.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
def test_worker_does_not_lose_answer_when_crash_between_mark_and_delete(tmp_path, monkeypatch):
    """If process dies between mark_answered and delete, the answer must survive (duplicate dispatch OK)."""
    from rufino.engine.qa.worker import poll_and_dispatch
    from rufino.engine.qa.store import QuestionStore
    from rufino.engine.qa.callback_registry import CallbackRegistry, Callback

    vault = tmp_path / "vault"
    state = tmp_path / "state"
    (vault / "questions").mkdir(parents=True)
    state.mkdir()

    store = QuestionStore(vault / "questions")
    registry = CallbackRegistry(state / "callbacks.json")
    slug = "q1"
    store.write_question(slug=slug, question="what?")
    registry.register(slug, Callback(adapter_name="a", adapter_state={}))
    store.write_answer(slug, "yes")  # user answered

    # Simulate crash: registry.delete raises after mark_answered succeeds.
    real_delete = CallbackRegistry.delete
    def crash_delete(self, s):
        raise RuntimeError("simulated crash post-mark_answered")
    monkeypatch.setattr(CallbackRegistry, "delete", crash_delete)

    calls = []
    try:
        poll_and_dispatch(
            vault_root=vault, state_dir=state,
            handler=lambda **kw: calls.append(kw["answer"]),
        )
    except RuntimeError:
        pass

    # Restore + re-run: must NOT lose the answer (callback may run again, that's fine).
    monkeypatch.setattr(CallbackRegistry, "delete", real_delete)
    # Reload state from disk to simulate process restart.
    store2 = QuestionStore(vault / "questions")
    answer_still_visible_or_already_dispatched = (
        store2.get_answer(slug) is not None or len(calls) >= 1
    )
    assert answer_still_visible_or_already_dispatched
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_qa_worker.py -k "crash_between" -v
```
Expected: FAIL with current order (delete first → if delete crashes, callback gone AND answer marked = lost forever).

- [ ] **Step 3: Invert the order**

Replace lines 68-71 of `src/rufino/engine/qa/worker.py`:

```python
        # Mark answered BEFORE deleting the callback. If we crash between the
        # two steps the worst case is a duplicate dispatch on retry, which is
        # recoverable. The opposite order silently drops the user's answer.
        store.mark_answered(slug)
        registry.delete(slug)
        dispatched += 1
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_qa_worker.py -v
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/rufino/engine/qa/worker.py tests/test_qa_worker.py
git commit -m "fix(qa): mark_answered before delete to avoid losing user answers on crash"
```

---

### Task 9: Atomic write for QuestionStore.write_question

**Files:**
- Modify: `src/rufino/engine/qa/store.py`
- Test: `tests/test_qa_store.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
def test_write_question_is_atomic(tmp_path, monkeypatch):
    """A crash mid-write must leave the original (or no file), never a half-written one."""
    from rufino.engine.qa.store import QuestionStore
    store = QuestionStore(tmp_path)
    store.write_question(slug="q1", question="original")

    # Patch Path.replace to raise; the staged tmp must not corrupt the real file.
    orig_replace = type(tmp_path).replace
    def boom(self, target):
        raise OSError("simulated rename failure")
    monkeypatch.setattr(type(tmp_path), "replace", boom)
    try:
        store.write_question(slug="q1", question="new content")
    except OSError:
        pass
    monkeypatch.setattr(type(tmp_path), "replace", orig_replace)

    # Original content must still be intact.
    assert "original" in (tmp_path / "q1.md").read_text()
    # No stale .tmp left.
    assert not list(tmp_path.glob("*.tmp"))
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_qa_store.py -k "is_atomic" -v
```
Expected: FAIL (current `path.write_text` is not staged).

- [ ] **Step 3: Implement tmp+replace**

Modify the `write_question` method (around line 52). Replace the direct `path.write_text(...)` with:

```python
        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            tmp.write_text(content, encoding="utf-8")
            tmp.replace(path)
        finally:
            if tmp.exists():
                tmp.unlink()
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_qa_store.py -v
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/rufino/engine/qa/store.py tests/test_qa_store.py
git commit -m "fix(qa): atomic write_question via tmp+replace"
```

---

### Task 10: Ingest runner — mark_seen for orphan fact files

**Files:**
- Modify: `src/rufino/engine/ingest/runner.py:124-143`
- Test: `tests/test_ingest_runner_emit_fact.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
def test_emit_fact_does_not_orphan_when_raw_write_fails(tmp_path, monkeypatch):
    """If raw write fails after fact write succeeded, the fact must still mark_seen
    so the next run doesn't re-emit a duplicate."""
    # Setup: adapter with both destination_facts and destination_raw.
    # (Use existing test fixtures / helpers for adapter scaffolding.)
    from rufino.engine.ingest import runner as runner_mod

    vault, state, adapter_dir = _setup_emit_fact_adapter(
        tmp_path,
        with_raw=True,
        facts=[{"id": "f1", "value": "x"}],
    )

    # Patch raw_path.write_text to raise on first call only.
    real_write_text = type(tmp_path).write_text
    raw_calls = {"n": 0}
    def maybe_fail(self, *a, **kw):
        if "raw" in str(self):
            raw_calls["n"] += 1
            raise OSError("simulated disk full on raw write")
        return real_write_text(self, *a, **kw)
    monkeypatch.setattr(type(tmp_path), "write_text", maybe_fail)

    result1 = runner_mod.run_ingest(
        adapter_dir=adapter_dir, vault_root=vault, rufino_state_dir=state,
    )
    assert result1.errors  # raw write failed
    monkeypatch.setattr(type(tmp_path), "write_text", real_write_text)

    # Second run with raw write working should NOT re-emit f1 (it was marked seen).
    result2 = runner_mod.run_ingest(
        adapter_dir=adapter_dir, vault_root=vault, rufino_state_dir=state,
    )
    assert result2.facts_emitted == 0, "fact was re-emitted; orphan bug"
```

(Implementation note: write or reuse `_setup_emit_fact_adapter` based on existing fixtures in the test file.)

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_ingest_runner_emit_fact.py -k "does_not_orphan" -v
```
Expected: FAIL — second run emits f1 again.

- [ ] **Step 3: Restructure write order**

In `src/rufino/engine/ingest/runner.py`, replace lines 124-143 of `_run_emit_fact`:

```python
        fact_path.parent.mkdir(parents=True, exist_ok=True)
        fact_md = _serialize_fact_md(source=manifest.source_name, fact_id=fact_id, fact=fact)
        try:
            fact_path.write_text(fact_md, encoding="utf-8")
            if manifest.destination_raw:
                try:
                    raw_path = _safe_join(
                        vault_root,
                        _render_dest(manifest.destination_raw, fact=fact, today=today),
                    )
                except IngestPathError as e:
                    errors.append(str(e))
                    # fact_path was written — mark seen so we don't re-emit; user can
                    # retry the raw write next run by editing the manifest or clearing
                    # the bad path. Skip the emitted++ to keep the metric honest.
                    dedup.mark_seen(source=manifest.source_name, fact_id=fact_id)
                    continue
                raw_path.parent.mkdir(parents=True, exist_ok=True)
                raw_path.write_text(json.dumps(fact, indent=2), encoding="utf-8")
        except OSError as e:
            errors.append(f"write failed for {fact_id}: {e}")
            # Mark seen so we don't loop on the same broken write every run.
            dedup.mark_seen(source=manifest.source_name, fact_id=fact_id)
            continue

        dedup.mark_seen(source=manifest.source_name, fact_id=fact_id)
        emitted += 1
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_ingest_runner_emit_fact.py -v
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/rufino/engine/ingest/runner.py tests/test_ingest_runner_emit_fact.py
git commit -m "fix(ingest): mark_seen on any write failure to prevent orphan re-emits"
```

---

### Task 11: Memory loop installer — refuse re-install instead of clobbering

**Files:**
- Modify: `src/rufino/engine/memory_loop/installer.py`
- Test: `tests/test_memory_loop_installer.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
def test_install_refuses_overwrite_when_hook_already_exists(tmp_path):
    from rufino.engine.memory_loop.installer import (
        install_memory_loop, InstallationError,
    )
    from rufino.runtime.transaction_log import TransactionLog

    claude_home = tmp_path / "claude_home"
    (claude_home / "hooks").mkdir(parents=True)
    (claude_home / "hooks" / "rufino-memory-loop-init.sh").write_text("# existing user content\n")

    adapter_dir = _make_min_adapter(tmp_path)  # fixture / helper from existing tests
    log = TransactionLog(tmp_path / "log.json")

    with pytest.raises(InstallationError, match="already installed"):
        install_memory_loop(
            adapter_dir=adapter_dir,
            claude_home=claude_home,
            vault_path=tmp_path / "vault",
            log=log,
        )

    # Pre-existing content survived.
    assert "existing user content" in (
        claude_home / "hooks" / "rufino-memory-loop-init.sh"
    ).read_text()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_memory_loop_installer.py -k "refuses_overwrite" -v
```
Expected: FAIL (installer currently overwrites).

- [ ] **Step 3: Add a pre-check**

In `src/rufino/engine/memory_loop/installer.py`, before the existing `init_target = hooks_dir / ...` line:

```python
    init_target = hooks_dir / "rufino-memory-loop-init.sh"
    stop_target = hooks_dir / "rufino-memory-loop-stop.sh"
    remember_target = commands_dir / "remember.md"
    for existing in (init_target, stop_target, remember_target):
        if existing.exists():
            raise InstallationError(
                f"{existing.name} already installed at {existing.parent}; "
                f"run uninstall first"
            )
```

(Remove the duplicate `init_target = ...` etc. later in the function.)

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_memory_loop_installer.py -v
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/rufino/engine/memory_loop/installer.py tests/test_memory_loop_installer.py
git commit -m "fix(memory-loop): refuse re-install instead of clobbering prior state"
```

---

## Phase 4 — User-facing correctness

### Task 12: Make _NoopEmbeddings fail loudly

**Files:**
- Modify: `src/rufino/cli.py:22-26`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
def test_noop_embeddings_raises_instead_of_silently_returning_zeros():
    from rufino.cli import _NoopEmbeddings
    with pytest.raises(NotImplementedError, match="placeholder"):
        _NoopEmbeddings().embed("hello")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_cli.py -k "noop_embeddings_raises" -v
```
Expected: FAIL (currently returns zeros).

- [ ] **Step 3: Replace the noop body**

In `src/rufino/cli.py`, replace the `_NoopEmbeddings.embed` method:

```python
class _NoopEmbeddings:
    """Placeholder embedder. Will be replaced by Ollama wiring; meanwhile any
    semantic-mode call raises loudly rather than returning misleading zeros."""
    def embed(self, text: str) -> list[float]:
        raise NotImplementedError(
            "semantic mode requires a real embedder; "
            "placeholder _NoopEmbeddings cannot embed text"
        )
```

Then in the `query_cmd` (around line 148) and `mcp_server_cmd` (around line 166), wrap the embedder construction with a clear error message when `mode != "lexical"`:

```python
    if mode in ("semantic", "hybrid"):
        click.echo(
            "WARN: semantic mode uses placeholder embedder; results will not be meaningful "
            "until the real embedder is wired (Plan 10).",
            err=True,
        )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_cli.py -v
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/rufino/cli.py tests/test_cli.py
git commit -m "fix(cli): _NoopEmbeddings raises instead of returning silent garbage"
```

---

### Task 13: Materializer — bring state_dir creation inside transaction log

**Files:**
- Modify: `src/rufino/wizard/materializer.py:48-50`
- Test: `tests/test_wizard_materializer.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
def test_materialize_rolls_back_state_dir_if_we_created_it(tmp_path):
    from rufino.wizard.materializer import materialize, MaterializationResult
    from rufino.wizard.spec_schema import WizardSpec
    from types import MappingProxyType

    state_dir = tmp_path / "fresh_state"
    assert not state_dir.exists()
    # Spec that will fail later (missing vocabulary entry triggers early error path,
    # but state_dir is created before that check. Use a spec that fails inside the
    # apply_and_log section instead — e.g. vault_root parent unwritable).
    vault_root = tmp_path / "readonly_dir" / "vault"
    (tmp_path / "readonly_dir").mkdir()
    (tmp_path / "readonly_dir").chmod(0o500)
    try:
        spec = WizardSpec(
            vertical_name="t",
            entities=("note",),
            vocabulary=MappingProxyType({"note": "notes/<slug>.md"}),
            sources=(), processing=(), outputs=(),
        )
        result = materialize(
            spec=spec, vault_root=vault_root,
            claude_home=tmp_path / "claude_home",
            state_dir=state_dir,
        )
        assert not result.success
    finally:
        (tmp_path / "readonly_dir").chmod(0o700)

    # state_dir must not exist if we created it AND the materialization failed.
    assert not state_dir.exists(), "state_dir leaked after rollback"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_wizard_materializer.py -k "rolls_back_state_dir" -v
```
Expected: FAIL (state_dir persists).

- [ ] **Step 3: Detect-then-log the state_dir creation**

In `src/rufino/wizard/materializer.py`, replace lines 48-50:

```python
    state_dir_existed_before = state_dir.exists()
    state_dir.mkdir(parents=True, exist_ok=True)
    tx_log = TransactionLog(state_dir / f"materialize-{spec.vertical_name}.json")
    if not state_dir_existed_before:
        apply_and_log(
            tx_log,
            op="mkdir",
            target=str(state_dir),
            apply_fn=lambda: None,  # already created above; just record for rollback
            rollback="rmdir_if_empty",
        )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_wizard_materializer.py -v
```
Expected: all PASS. (Depends on Task 1 having registered `rmdir_if_empty`.)

- [ ] **Step 5: Commit**

```bash
git add src/rufino/wizard/materializer.py tests/test_wizard_materializer.py
git commit -m "fix(wizard): rollback newly-created state_dir on materialize failure"
```

---

### Task 14: upgrade.sh — semver ordering instead of plain equality

**Files:**
- Modify: `upgrade.sh:49`
- Test: `tests/integration/test_upgrade_semver.sh` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_upgrade_semver.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
# Smoke: upgrade.sh must refuse to downgrade.
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export RUFINO_HOME="$TMP/.rufino"
mkdir -p "$RUFINO_HOME"
echo "9.9.9" > "$RUFINO_HOME/version"  # pretend a newer version is installed
# We expect upgrade.sh to exit non-zero with a "refusing downgrade" message.
output="$(./upgrade.sh 2>&1)" || rc=$? && rc=${rc:-0}
[ "$rc" -ne 0 ] || { echo "FAIL: upgrade.sh allowed downgrade"; exit 1; }
echo "$output" | grep -qi "downgrade" || { echo "FAIL: missing downgrade message"; exit 1; }
echo "OK: downgrade blocked"
```

Make executable:
```bash
chmod +x tests/integration/test_upgrade_semver.sh
```

- [ ] **Step 2: Run test to verify it fails**

```bash
./tests/integration/test_upgrade_semver.sh
```
Expected: FAIL (current upgrade.sh treats `9.9.9 != 0.0.1` as upgrade-ahead and proceeds).

- [ ] **Step 3: Add semver ordering**

In `upgrade.sh`, replace lines 49-52 with:

```bash
# Compare semver: refuse downgrades unless RUFINO_FORCE=1.
semver_gt() {
    # returns 0 if $1 > $2
    [ "$1" = "$2" ] && return 1
    local higher
    higher="$(printf '%s\n%s\n' "$1" "$2" | sort -V | tail -n1)"
    [ "$higher" = "$1" ]
}

if [ "$INSTALLED" = "$CURRENT" ]; then
    echo "==> Already at $CURRENT. Nothing to do."
    exit 0
fi

if semver_gt "$INSTALLED" "$CURRENT"; then
    if [ "${RUFINO_FORCE:-0}" != "1" ]; then
        echo "ERROR: refusing downgrade from $INSTALLED to $CURRENT." >&2
        echo "       Set RUFINO_FORCE=1 to override." >&2
        exit 1
    fi
    echo "==> WARN: forced downgrade $INSTALLED → $CURRENT"
fi
```

- [ ] **Step 4: Run test to verify it passes**

```bash
./tests/integration/test_upgrade_semver.sh
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add upgrade.sh tests/integration/test_upgrade_semver.sh
git commit -m "fix(distribution): upgrade.sh refuses downgrades (semver ordering)"
```

---

### Task 15: install.sh — use `claude mcp add` (or update jq write to support re-link)

**Files:**
- Modify: `install.sh:107-133`

- [ ] **Step 1: Inspect current behavior + decide branching**

Read `install.sh:107-133`. The current code uses `jq -e` to skip registration if any entry exists. Update to **detect-and-update** instead of detect-and-skip, so re-running install with a different `RUFINO_VAULT` updates the registered args.

- [ ] **Step 2: Replace the registration block**

Replace lines 107-133 of `install.sh`:

```bash
# --- Register/update MCP server in Claude Code config
CLAUDE_CONFIG="$HOME/.claude.json"
if ! command -v jq >/dev/null 2>&1; then
    echo "WARN: jq not found; skipping MCP registration. Install jq and re-run." >&2
else
    if [ ! -f "$CLAUDE_CONFIG" ]; then
        echo '{"mcpServers": {}}' > "$CLAUDE_CONFIG"
    fi
    # Ensure mcpServers key exists.
    tmp_cfg="$(mktemp)"
    jq '.mcpServers = (.mcpServers // {})' "$CLAUDE_CONFIG" > "$tmp_cfg"
    mv "$tmp_cfg" "$CLAUDE_CONFIG"
    # Write/overwrite the ask-rufino entry with the current vault path.
    tmp_cfg="$(mktemp)"
    jq --arg cmd "$RUFINO_BIN" --arg vault "$RUFINO_VAULT" \
       '.mcpServers["ask-rufino"] = {command: $cmd, args: ["mcp-server", "--vault", $vault]}' \
       "$CLAUDE_CONFIG" > "$tmp_cfg"
    mv "$tmp_cfg" "$CLAUDE_CONFIG"
    echo "==> Registered ask-rufino MCP (vault: $RUFINO_VAULT)"
fi
```

- [ ] **Step 3: Sanity check by running installer twice with different vaults**

```bash
RUFINO_VAULT=/tmp/vault1 ./install.sh
RUFINO_VAULT=/tmp/vault2 ./install.sh
jq '.mcpServers["ask-rufino"].args' ~/.claude.json
# Expected: ["mcp-server", "--vault", "/tmp/vault2"]
```

- [ ] **Step 4: Commit**

```bash
git add install.sh
git commit -m "fix(distribution): install.sh updates MCP registration on re-run"
```

---

## Phase 5 — Important hardening

### Task 16: Output dispatcher — idempotency key + partial-failure handling

**Files:**
- Modify: `src/rufino/engine/output/dispatcher.py:61-74`
- Test: `tests/test_output_dispatcher.py`

- [ ] **Step 1: Write the failing tests**

Append:

```python
def test_unknown_channel_does_not_short_circuit_other_deliveries(tmp_path):
    """If delivery[0] succeeds and delivery[1] uses an unknown channel,
    the success of [0] must be recorded; [1] becomes an error entry."""
    # (Use existing fixture pattern; assert OutputResult.errors has the unknown-channel
    #  entry AND deliveries_succeeded == 1.)
    ...


def test_idempotency_key_prevents_double_delivery_on_retry(tmp_path):
    """Two runs of the same digest with same content hash should not re-send."""
    ...
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_output_dispatcher.py -k "unknown_channel_does_not or idempotency_key" -v
```

- [ ] **Step 3: Implement**

In `dispatcher.py`, convert the unknown-channel `raise` into an error-entry append; add an `idempotency_keys.json` file in state_dir keyed by `sha256(adapter_name + delivery_index + content)`; skip + log if already sent.

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_output_dispatcher.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/rufino/engine/output/dispatcher.py tests/test_output_dispatcher.py
git commit -m "fix(output): record partial failures + idempotency keys for retries"
```

---

### Task 17: Email channel TLS hardening

**Files:**
- Modify: `src/rufino/engine/output/channels/email_channel.py`
- Test: `tests/test_output_channel_email.py`

- [ ] **Step 1: Write the failing tests**

Append:

```python
def test_email_uses_smtps_when_port_465():
    """Port 465 must use SMTP_SSL, not STARTTLS."""
    ...


def test_email_refuses_to_login_when_starttls_unsupported(monkeypatch):
    """If server lacks STARTTLS extension, raise instead of logging in over plaintext."""
    ...
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_output_channel_email.py -k "smtps or starttls_unsupported" -v
```

- [ ] **Step 3: Implement**

Choose `SMTP_SSL` when `port == 465`. After `starttls()` succeeds, verify with `s.has_extn("starttls")` BEFORE calling login. Build SSL context with `ssl.create_default_context()` explicitly.

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_output_channel_email.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/rufino/engine/output/channels/email_channel.py tests/test_output_channel_email.py
git commit -m "fix(output): email channel TLS hardening (SMTPS on 465 + STARTTLS check)"
```

---

### Task 18: Lexical query — escape regex metachars / use fixed-string

**Files:**
- Modify: `src/rufino/engine/query/lexical.py`
- Test: `tests/test_query_lexical.py`

- [ ] **Step 1: Write the failing tests**

Append:

```python
@pytest.mark.parametrize("query,expected_in_results", [
    ("c++", True),
    ("a.b", True),
    ("f(x)", True),
    ("[draft]", True),
])
def test_lexical_handles_regex_metachars_as_literal(tmp_path, query, expected_in_results):
    """Queries with regex special chars must match the literal text, not the regex."""
    # Create a vault note containing each literal string, run lexical_search,
    # assert the note is found.
    ...
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_query_lexical.py -k "regex_metachars" -v
```

- [ ] **Step 3: Implement**

In `lexical.py`, pass `-F` (fixed-string) to ripgrep AND change the Python fallback to use substring match (case-sensitive) so both paths have identical semantics. Pseudocode:

```python
cmd = ["rg", "-l", "-F", "--", query, str(vault_root)]
# ...
# Fallback:
return [p for p in iter_user_notes(vault_root) if query in p.read_text(errors="replace")]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_query_lexical.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/rufino/engine/query/lexical.py tests/test_query_lexical.py
git commit -m "fix(query): treat lexical queries as fixed-strings (regex metachar safety)"
```

---

### Task 19: MCP server — constrain schemas + redact error messages

**Files:**
- Modify: `src/rufino/mcp_server/server.py`, `src/rufino/mcp_server/tools.py`
- Test: `tests/test_mcp_tools.py`

- [ ] **Step 1: Write the failing tests**

Append:

```python
def test_search_schema_constrains_mode_to_enum():
    from rufino.mcp_server.server import list_tools
    tools = list_tools()
    search = next(t for t in tools if t["name"] == "search_vault")
    assert search["inputSchema"]["properties"]["mode"]["enum"] == ["lexical", "semantic", "hybrid"]
    assert search["inputSchema"]["properties"]["k"]["minimum"] == 1
    assert search["inputSchema"]["properties"]["k"]["maximum"] == 100


def test_tool_handler_errors_do_not_leak_vault_path(tmp_path, monkeypatch):
    """Internal exceptions must surface as redacted messages, not absolute paths."""
    from rufino.mcp_server import server as srv
    # Force a handler to raise with the absolute vault path in the message.
    # Assert client-visible response does not contain str(vault_root).
    ...
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_mcp_tools.py -k "constrains_mode or do_not_leak" -v
```

- [ ] **Step 3: Implement**

In `server.py:list_tools`, add `"enum": ["lexical","semantic","hybrid"]` and `"minimum": 1, "maximum": 100, "default": 10` for `k`. In `call_tool` dispatch, wrap `_HANDLERS[name](...)` in try/except and replace any string containing `str(ql.vault_root)` with `"<vault>"` before returning to the client. Log the full detail server-side.

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_mcp_tools.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/rufino/mcp_server/server.py src/rufino/mcp_server/tools.py tests/test_mcp_tools.py
git commit -m "fix(mcp): constrain tool input schemas + redact vault paths in errors"
```

---

### Task 20: Wizard spec_schema — validate vocabulary keys against entities + entity-name regex

**Files:**
- Modify: `src/rufino/wizard/spec_schema.py:117-119`
- Test: `tests/test_wizard_spec_schema.py`

- [ ] **Step 1: Write the failing tests**

Append:

```python
def test_validate_spec_rejects_vocabulary_key_not_in_entities():
    from rufino.wizard.spec_schema import validate_spec, SpecValidationError
    spec_dict = {
        "vertical_name": "t",
        "entities": ["note"],
        "vocabulary": {"note": "notes/<slug>.md", "ghost": "ghost/<slug>.md"},
        "sources": [], "processing": [], "outputs": [],
    }
    with pytest.raises(SpecValidationError, match="ghost"):
        validate_spec(spec_dict)


def test_validate_spec_rejects_invalid_vocabulary_key_chars():
    from rufino.wizard.spec_schema import validate_spec, SpecValidationError
    spec_dict = {
        "vertical_name": "t",
        "entities": ["note", "with space"],  # invalid entity
        "vocabulary": {"note": "notes/<slug>.md", "with space": "x/<slug>.md"},
        "sources": [], "processing": [], "outputs": [],
    }
    with pytest.raises(SpecValidationError):
        validate_spec(spec_dict)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_wizard_spec_schema.py -k "rejects_vocabulary or invalid_vocabulary_key" -v
```

- [ ] **Step 3: Add the checks**

In `spec_schema.py:_validate_vocabulary` (around line 117), add:

```python
    entities_set = set(spec["entities"])
    extra = set(vocabulary.keys()) - entities_set
    if extra:
        raise SpecValidationError(
            f"vocabulary keys not declared as entities: {sorted(extra)}"
        )
    for k in vocabulary.keys():
        if not _ENTITY_NAME_RE.match(k):
            raise SpecValidationError(
                f"invalid vocabulary key {k!r}: must match {_ENTITY_NAME_RE.pattern}"
            )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_wizard_spec_schema.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/rufino/wizard/spec_schema.py tests/test_wizard_spec_schema.py
git commit -m "fix(wizard): validate vocabulary keys against entities + name regex"
```

---

## Phase 6 — Codex Additions

### Task 21: qa-poll must not consume callbacks with the placeholder handler

**Why:** `rufino qa-poll` currently wires `_noop_handler`, but `poll_and_dispatch()` treats any non-raising handler call as a successful dispatch. That archives the answered question and deletes the callback without resuming the original adapter.

**Files:**
- Modify: `src/rufino/cli.py:121-138`
- Test: `tests/test_cli_qa_poll.py` and/or `tests/test_qa_worker.py`

- [ ] **Step 1: Write the failing test**

Create a pending callback + answered question, invoke the CLI `qa-poll`, and assert the callback is still present and the question is still in `questions/` when real resumption is unavailable.

Implementation sketch:

```python
def test_cli_qa_poll_does_not_consume_when_resumption_unimplemented(tmp_path):
    from click.testing import CliRunner
    from rufino.cli import cli
    from rufino.engine.qa.store import QuestionStore
    from rufino.engine.qa.callback_registry import CallbackRegistry, PendingCallback

    vault = tmp_path / "vault"
    state = tmp_path / "state"
    store = QuestionStore(vault / "questions")
    registry = CallbackRegistry(state / "callbacks.json")
    slug = "q1"
    store.write_question(slug=slug, template_name="t", body="Question?")
    (vault / "questions" / f"{slug}.md").write_text(
        "---\ntemplate_name: t\nanswer: \"yes\"\n---\nQuestion?\n",
        encoding="utf-8",
    )
    registry.register(PendingCallback(
        question_slug=slug, adapter_name="adapter", adapter_state={"x": 1},
    ))

    result = CliRunner().invoke(cli, [
        "qa-poll", "--vault", str(vault), "--state-dir", str(state),
    ])

    assert result.exit_code != 0
    assert registry.get(slug) is not None
    assert (vault / "questions" / f"{slug}.md").exists()
```

- [ ] **Step 2: Implement**

Until real adapter resumption exists, make `qa-poll` exit non-zero before calling `poll_and_dispatch()`, or pass a handler that raises a dedicated `NotImplementedError` so `poll_and_dispatch()` leaves the callback and question in place. Prefer the first option for user clarity:

```python
    click.echo(
        "Error: qa-poll adapter resumption is not wired yet; refusing to consume answers.",
        err=True,
    )
    raise click.exceptions.Exit(code=2)
```

- [ ] **Step 3: Verify**

```bash
pytest tests/test_cli_qa_poll.py tests/test_qa_worker.py -v
```

- [ ] **Step 4: Commit**

```bash
git add src/rufino/cli.py tests/test_cli_qa_poll.py tests/test_qa_worker.py
git commit -m "fix(cli): qa-poll refuses to consume answers until resumption is wired"
```

---

### Task 22: Materializer must create the vault skeleton promised by docs and required by process light

**Why:** A freshly materialized vault has `questions/` and `perfil.md`, but no `inbox/` or `_meta/` files. The generated README tells users to drop files in `inbox/`, and `_process_light()` writes `_meta/_tags.md` / `_processing-log.md` without creating the parent.

**Files:**
- Modify: `src/rufino/wizard/materializer.py`
- Modify: `src/rufino/engine/process/helpers/indices.py`
- Test: `tests/test_wizard_materializer.py`, `tests/test_process_dispatcher_light.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_wizard_materializer.py`:

```python
def test_materialize_creates_operational_vault_dirs_and_meta_files(tmp_path):
    spec = validate_spec(MINIMAL_SPEC)
    vault = tmp_path / "vault"
    result = materialize(
        spec=spec,
        vault_root=vault,
        claude_home=tmp_path / ".claude",
        state_dir=tmp_path / ".rufino-state",
    )
    assert result.success, result.errors
    assert (vault / "inbox").is_dir()
    assert (vault / "_meta" / "_tags.md").exists()
    assert (vault / "_meta" / "_processing-log.md").exists()
```

Append to `tests/test_process_dispatcher_light.py`:

```python
def test_light_mode_creates_meta_parent_if_missing(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "note.md"
    note.write_text("---\ntags: [x]\n---\nbody\n", encoding="utf-8")

    result = process_note(note_path=note, vault_root=vault, mode="light")

    assert result.success
    assert (vault / "_meta" / "_tags.md").exists()
    assert (vault / "_meta" / "_processing-log.md").exists()
```

- [ ] **Step 2: Implement**

In `materialize()`, transactionally create:

- `inbox/`
- `_meta/`
- `_meta/_tags.md` initialized to `# Tags\n`
- `_meta/_processing-log.md` initialized to `# Processing log\n`

In `update_tag_index()` and `append_to_log()`, ensure `path.parent.mkdir(parents=True, exist_ok=True)` before reading/writing.

- [ ] **Step 3: Verify**

```bash
pytest tests/test_wizard_materializer.py tests/test_process_dispatcher_light.py -v
```

- [ ] **Step 4: Commit**

```bash
git add src/rufino/wizard/materializer.py src/rufino/engine/process/helpers/indices.py tests/test_wizard_materializer.py tests/test_process_dispatcher_light.py
git commit -m "fix(wizard): materialize operational vault skeleton"
```

---

### Task 23: rufino output must use the real query layer or fail loudly

**Why:** `rufino output` advertises that it runs an Output adapter, but it passes `StubQueryLayer()` to the dispatcher. Real manifests render with empty query results even when the vault has matching notes.

**Files:**
- Modify: `src/rufino/cli.py:103-118`
- Test: `tests/test_cli_output.py`

- [ ] **Step 1: Write the failing test**

Use a temporary vault with a matching note and an output adapter whose template renders query results. Invoke the CLI and assert the written file contains the note path.

Implementation sketch:

```python
def test_output_cli_uses_real_query_layer(tmp_path):
    from click.testing import CliRunner
    from rufino.cli import cli

    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "note.md").write_text("regresion logistica", encoding="utf-8")

    adapter = tmp_path / "adapter"
    adapter.mkdir()
    (adapter / "manifest.yaml").write_text(
        """
adapter_name: digest
trigger: {type: cron, expression: "0 8 * * *"}
query:
  - {name: hits, expression: "regresion"}
template: template.md
delivery:
  - {channel: file, path: out.md}
""",
        encoding="utf-8",
    )
    (adapter / "template.md").write_text("{{ query.hits|join('\\n') }}", encoding="utf-8")

    result = CliRunner().invoke(cli, ["output", str(adapter), "--vault", str(vault)])

    assert result.exit_code == 0
    assert "note.md" in (vault / "out.md").read_text(encoding="utf-8")
```

- [ ] **Step 2: Implement**

Because `_NoopEmbeddings` should fail loudly after Task 12, wire `output_cmd` to a lexical-only adapter for `query.run()` or make `QueryLayer.run()` support a configured default mode. Minimal fix:

```python
class _LexicalQueryAdapter:
    def __init__(self, vault_root: Path) -> None:
        self._ql = QueryLayer(vault_root=vault_root, embedder=_NoopEmbeddings())

    def run(self, query_string: str) -> list[str]:
        return [r.relative_path for r in self._ql.search(query_string, mode="lexical")]
```

Then pass `_LexicalQueryAdapter(vault_root)` instead of `StubQueryLayer()`.

- [ ] **Step 3: Verify**

```bash
pytest tests/test_cli_output.py tests/test_output_dispatcher.py -v
```

- [ ] **Step 4: Commit**

```bash
git add src/rufino/cli.py tests/test_cli_output.py
git commit -m "fix(cli): output command uses real lexical query results"
```

---

### Task 24: Register ask-rufino MCP after materialize/bootstrap creates the vault

**Why:** `install.sh` can only register MCP when `RUFINO_VAULT` already exists, while README and installer comments say bootstrap will register after materialization. Currently neither `bootstrap` nor `materialize` writes `.claude.json`.

**Files:**
- Modify: `src/rufino/cli.py`
- Add or modify: a small helper module such as `src/rufino/runtime/claude_config.py`
- Test: `tests/test_cli_wizard.py` or `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

Invoke `rufino materialize --spec ... --vault ... --claude-home ... --state-dir ...` with a temporary `HOME`, then assert `$HOME/.claude.json` contains:

```json
{
  "mcpServers": {
    "ask-rufino": {
      "command": ".../rufino",
      "args": ["mcp-server", "--vault", "<vault>"]
    }
  }
}
```

The exact command can be `sys.argv[0]`/installed `rufino` when available, but the test should only require that the args point at the materialized vault.

- [ ] **Step 2: Implement**

Add a JSON helper that:

- creates `.claude.json` if missing
- preserves unrelated keys
- creates or updates `.mcpServers["ask-rufino"]`
- writes atomically via tmp+replace

Call it from `materialize_cmd` after `result.success`, because at that point the vault path is known and exists. Keep `install.sh` Task 15 as the pre-existing-vault path.

- [ ] **Step 3: Verify**

```bash
pytest tests/test_cli_wizard.py tests/test_cli.py -v
```

- [ ] **Step 4: Commit**

```bash
git add src/rufino/cli.py src/rufino/runtime/claude_config.py tests/test_cli_wizard.py tests/test_cli.py
git commit -m "fix(cli): register ask-rufino MCP after materialize"
```

---

### Task 25: Enforce or remove allow_network in transform sandbox

**Why:** `run_transform_hook(..., allow_network=False)` accepts a security-sensitive flag but does not enforce it. PATH stripping does not stop Python code from importing `socket`, `urllib`, or `http.client`.

**Files:**
- Modify: `src/rufino/runtime/sandbox.py`
- Test: `tests/test_sandbox.py`

- [ ] **Step 1: Decide contract**

Preferred for v0.1: fail closed unless a real network sandbox is available. If `allow_network=False`, inject a Python startup guard that blocks common networking modules for hook code. If that is too brittle for v0.1, remove the parameter and update docs/tests so callers cannot assume isolation.

- [ ] **Step 2: Write failing test**

Create a hook that imports `socket` and attempts to connect or resolve a host. Assert `allow_network=False` fails before the hook can report success, while `allow_network=True` preserves current behavior.

- [ ] **Step 3: Implement**

For the fail-closed v0.1 option, run hooks through a small wrapper script that patches `socket.socket`, `socket.create_connection`, and DNS helpers when `allow_network=False`, then executes the target hook with `runpy.run_path()`. Keep the existing timeout and isolated cwd behavior.

- [ ] **Step 4: Verify**

```bash
pytest tests/test_sandbox.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/rufino/runtime/sandbox.py tests/test_sandbox.py
git commit -m "fix(runtime): enforce allow_network in transform sandbox"
```

---

## Final verification

After all 25 tasks land:

- [ ] **Step 1: Full test suite green**

```bash
pytest -q
```
Expected: 0 failures, 0 errors. Note the new total count (was ~baseline + the new tests from each task).

- [ ] **Step 2: Coverage check on touched modules**

```bash
pytest --cov=src/rufino/runtime --cov=src/rufino/engine --cov=src/rufino/wizard --cov=src/rufino/mcp_server --cov-report=term-missing
```
Spot-check that the modules we modified have ≥80% line coverage on the new code paths.

- [ ] **Step 3: Bump VERSION to 0.0.2 and tag**

```bash
# Edit pyproject.toml and src/rufino/version.py to 0.0.2
pytest tests/test_version_sync.py -v  # must still pass
git add pyproject.toml src/rufino/version.py
git commit -m "chore: bump version 0.0.1 → 0.0.2 (review-fix sprint)"
git tag v0.0.2
```

- [ ] **Step 4: Manual smoke of install + upgrade**

```bash
./install.sh
./upgrade.sh   # should report "Already at 0.0.2. Nothing to do."
RUFINO_FORCE=0 ./upgrade.sh  # noop again
```

- [ ] **Step 5: Update the project log in the vault**

After completion, ask Claude to dispatch a vault-memory subagent that appends "Sprint de estabilización completado (2026-MM-DD): 25 fixes aplicados, v0.0.2 tagged" to `proyectos/rufino/rufino-framework/logPlan9InstallerDistribution.md`.

---

## Plan summary

| Phase | Tasks | Impact |
|---|---|---|
| 1 — Foundation | 3 | Restores big-bang guarantee; locks version drift out of CI |
| 2 — Security | 4 | Closes path traversal, prompt injection, SSRF, XML injection |
| 3 — Data integrity | 4 | Eliminates lost-answer, orphan-fact, clobber-on-reinstall scenarios |
| 4 — User-facing correctness | 4 | Loud failures + safer install/upgrade flow |
| 5 — Important hardening | 5 | Output retries, TLS, lexical correctness, MCP schemas, spec validation |
| 6 — Codex additions | 5 | Prevents no-op answer consumption, completes vault skeleton, removes stubbed output query, registers MCP post-materialize, enforces sandbox network flag |

**Estimated effort:** ~8-10 hours for an engineer who reads each file before touching it. TDD steps prevent overshooting.
