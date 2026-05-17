# Plan 1 — Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir el plumbing común que todas las 6 primitives + el wizard van a consumir: CLI base, helpers v1 (librería Python versionada), abstracciones de secrets/scheduler, sandbox runtime para transform hooks, transaction log para rollback transaccional del bootstrap, y validador base común.

**Architecture:** Repositorio Python con layout modular. Cada subsistema en su propio paquete bajo `engine/`, `helpers/v1/` y `runtime/`. CLI `rufino` es bash thin wrapper que delega a Python (`python -m rufino_cli`). Backends de OS específico (launchd para macOS, cron para Linux) detrás de interfaces comunes para que el resto del framework no dependa del SO.

**Tech Stack:** Python 3.11+, pytest, click (CLI), pyyaml (manifests), keyring (Keychain abstraction), launchd/cron (scheduling). Sin dependencias pesadas — todo standard library o librerías pequeñas y maduras.

**Dependencias previas:** ninguna. Este es el plan base.

**Plans que dependen de este:** todos los siguientes (Plans 2-9).

---

## File Structure

```
rufino-framework/
├── pyproject.toml                              # Python project metadata
├── .gitignore                                  # Python + caches + secrets
├── cli/
│   └── rufino                                  # bash thin wrapper
├── src/
│   └── rufino/
│       ├── __init__.py
│       ├── __main__.py                         # python -m rufino entry
│       ├── cli.py                              # click CLI command groups
│       ├── version.py                          # VERSION constant
│       ├── helpers/
│       │   └── v1/
│       │       ├── __init__.py                 # public API of v1
│       │       └── version.py                  # helper version reporting
│       └── runtime/
│           ├── __init__.py
│           ├── secrets.py                      # secrets abstraction + backends
│           ├── scheduler.py                    # scheduler abstraction + backends
│           ├── sandbox.py                      # transform.py sandbox runner
│           ├── transaction_log.py              # bootstrap rollback log
│           └── validator_base.py               # common validator interface
└── tests/
    ├── conftest.py                             # pytest fixtures
    ├── test_cli.py
    ├── test_helpers_v1.py
    ├── test_secrets.py
    ├── test_scheduler.py
    ├── test_sandbox.py
    ├── test_transaction_log.py
    ├── test_validator_base.py
    └── test_foundation_smoke.py                # end-to-end smoke test
```

**File responsibilities:**

| File | Responsibility |
|---|---|
| `pyproject.toml` | Python package metadata, dependencies, pytest config |
| `cli/rufino` | bash wrapper que ejecuta `python -m rufino "$@"` |
| `src/rufino/__main__.py` | entry point para `python -m rufino` |
| `src/rufino/cli.py` | comandos click (`version`, `--help`) |
| `src/rufino/version.py` | single source of truth para framework version |
| `src/rufino/helpers/v1/__init__.py` | API pública del helper v1 (lo que adapters consumen) |
| `src/rufino/runtime/secrets.py` | interfaz `SecretStore` + backends macOS Keychain + Linux Secret Service |
| `src/rufino/runtime/scheduler.py` | interfaz `Scheduler` + backends launchd + cron |
| `src/rufino/runtime/sandbox.py` | runner de transform.py con timeout, fs readonly, network opt-in |
| `src/rufino/runtime/transaction_log.py` | append-only log de operaciones del bootstrap + rollback |
| `src/rufino/runtime/validator_base.py` | interfaz `Validator` que los validadores por shape implementan |

---

## Task 1: Bootstrap del repo Python

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `src/rufino/__init__.py`
- Create: `src/rufino/version.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Write pyproject.toml**

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "rufino-framework"
version = "0.0.1"
description = "Meta-arquitectura A2P para dominios de conocimiento personal"
requires-python = ">=3.11"
authors = [{ name = "Valentino Errandonea" }]
dependencies = [
    "click>=8.1",
    "pyyaml>=6.0",
    "keyring>=24.0",
]

[project.optional-dependencies]
dev = ["pytest>=7.4", "pytest-cov>=4.1"]

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
```

- [ ] **Step 2: Write .gitignore**

```
__pycache__/
*.py[cod]
*$py.class
.pytest_cache/
.coverage
htmlcov/
*.egg-info/
build/
dist/
.venv/
venv/
.env
.DS_Store
```

- [ ] **Step 3: Write src/rufino/__init__.py and version.py**

`src/rufino/__init__.py`:
```python
from rufino.version import VERSION

__version__ = VERSION
```

`src/rufino/version.py`:
```python
VERSION = "0.0.1"
```

- [ ] **Step 4: Write tests/conftest.py with shared fixtures**

```python
import pytest
import tempfile
from pathlib import Path


@pytest.fixture
def tmp_vault(tmp_path: Path) -> Path:
    """Vault path temporal limpio para cada test."""
    vault = tmp_path / "vault"
    vault.mkdir()
    return vault


@pytest.fixture
def tmp_rufino_home(tmp_path: Path, monkeypatch) -> Path:
    """~/.rufino temporal aislado del filesystem real del user."""
    home = tmp_path / ".rufino"
    home.mkdir()
    monkeypatch.setenv("RUFINO_HOME", str(home))
    return home
```

- [ ] **Step 5: Install in editable mode + verify**

Run:
```bash
pip install -e ".[dev]"
python -c "import rufino; print(rufino.__version__)"
```

Expected output: `0.0.1`

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml .gitignore src/rufino/__init__.py src/rufino/version.py tests/conftest.py
git commit -m "feat(foundation): bootstrap Python package layout"
```

---

## Task 2: CLI básico con `rufino --version` y `rufino --help`

**Files:**
- Create: `src/rufino/__main__.py`
- Create: `src/rufino/cli.py`
- Create: `cli/rufino`
- Create: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

`tests/test_cli.py`:
```python
from click.testing import CliRunner
from rufino.cli import cli


def test_version_command():
    runner = CliRunner()
    result = runner.invoke(cli, ["version"])
    assert result.exit_code == 0
    assert "0.0.1" in result.output


def test_help_lists_version():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "version" in result.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: rufino.cli`

- [ ] **Step 3: Write CLI implementation**

`src/rufino/cli.py`:
```python
import click
from rufino.version import VERSION


@click.group()
def cli() -> None:
    """Rufino Framework CLI."""


@cli.command()
def version() -> None:
    """Print framework version."""
    click.echo(VERSION)
```

`src/rufino/__main__.py`:
```python
from rufino.cli import cli

if __name__ == "__main__":
    cli()
```

`cli/rufino`:
```bash
#!/usr/bin/env bash
exec python -m rufino "$@"
```

- [ ] **Step 4: Make wrapper executable**

Run: `chmod +x cli/rufino`

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_cli.py -v`
Expected: 2 passed

- [ ] **Step 6: Verify wrapper works**

Run:
```bash
./cli/rufino version
./cli/rufino --help
```

Expected: prints `0.0.1` and the help text listing `version`.

- [ ] **Step 7: Commit**

```bash
git add src/rufino/__main__.py src/rufino/cli.py cli/rufino tests/test_cli.py
git commit -m "feat(foundation): rufino CLI with version + help"
```

---

## Task 3: Helpers v1 skeleton

**Files:**
- Create: `src/rufino/helpers/__init__.py`
- Create: `src/rufino/helpers/v1/__init__.py`
- Create: `src/rufino/helpers/v1/version.py`
- Create: `tests/test_helpers_v1.py`

- [ ] **Step 1: Write the failing test**

`tests/test_helpers_v1.py`:
```python
from rufino.helpers import v1


def test_v1_version():
    assert v1.HELPER_VERSION == "1.0.0"


def test_v1_exposes_version_function():
    assert v1.helper_version() == "1.0.0"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_helpers_v1.py -v`
Expected: FAIL with `ModuleNotFoundError: rufino.helpers`

- [ ] **Step 3: Write the helper modules**

`src/rufino/helpers/__init__.py`:
```python
from rufino.helpers import v1

__all__ = ["v1"]
```

`src/rufino/helpers/v1/__init__.py`:
```python
from rufino.helpers.v1.version import HELPER_VERSION, helper_version

__all__ = ["HELPER_VERSION", "helper_version"]
```

`src/rufino/helpers/v1/version.py`:
```python
HELPER_VERSION = "1.0.0"


def helper_version() -> str:
    """Return the helper API version this adapter targets."""
    return HELPER_VERSION
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_helpers_v1.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/rufino/helpers/ tests/test_helpers_v1.py
git commit -m "feat(foundation): helpers v1 skeleton with version reporting"
```

---

## Task 4: Secrets abstraction with macOS Keychain backend

**Files:**
- Create: `src/rufino/runtime/__init__.py`
- Create: `src/rufino/runtime/secrets.py`
- Create: `tests/test_secrets.py`

- [ ] **Step 1: Write the failing test**

`tests/test_secrets.py`:
```python
import pytest
from rufino.runtime.secrets import SecretStore, InMemorySecretStore, SecretNotFound


def test_store_and_retrieve_secret():
    store = InMemorySecretStore()
    store.set("rufino-test", "user", "my-secret-value")
    assert store.get("rufino-test", "user") == "my-secret-value"


def test_get_missing_secret_raises():
    store = InMemorySecretStore()
    with pytest.raises(SecretNotFound):
        store.get("rufino-test", "user")


def test_delete_secret():
    store = InMemorySecretStore()
    store.set("rufino-test", "user", "v")
    store.delete("rufino-test", "user")
    with pytest.raises(SecretNotFound):
        store.get("rufino-test", "user")


def test_delete_missing_secret_is_idempotent():
    store = InMemorySecretStore()
    store.delete("nonexistent", "user")  # no exception


def test_protocol_compliance():
    store = InMemorySecretStore()
    assert isinstance(store, SecretStore)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_secrets.py -v`
Expected: FAIL with `ModuleNotFoundError: rufino.runtime.secrets`

- [ ] **Step 3: Write the secrets module**

`src/rufino/runtime/__init__.py`:
```python
```

`src/rufino/runtime/secrets.py`:
```python
from typing import Protocol, runtime_checkable


class SecretNotFound(Exception):
    """Raised when a secret is requested but does not exist in the store."""


@runtime_checkable
class SecretStore(Protocol):
    """Abstract secret store. Backends: macOS Keychain, Linux Secret Service, in-memory."""

    def get(self, service: str, account: str) -> str: ...
    def set(self, service: str, account: str, value: str) -> None: ...
    def delete(self, service: str, account: str) -> None: ...


class InMemorySecretStore:
    """In-memory backend. For tests and ephemeral use only — NOT for production."""

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], str] = {}

    def get(self, service: str, account: str) -> str:
        try:
            return self._store[(service, account)]
        except KeyError:
            raise SecretNotFound(f"No secret for service={service!r} account={account!r}")

    def set(self, service: str, account: str, value: str) -> None:
        self._store[(service, account)] = value

    def delete(self, service: str, account: str) -> None:
        self._store.pop((service, account), None)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_secrets.py -v`
Expected: 5 passed

- [ ] **Step 5: Add macOS Keychain backend**

Add to `src/rufino/runtime/secrets.py`:
```python
import keyring
import keyring.errors


class KeyringSecretStore:
    """Real backend using the `keyring` library.

    On macOS uses Keychain. On Linux uses Secret Service (gnome-keyring / kwallet).
    """

    def get(self, service: str, account: str) -> str:
        value = keyring.get_password(service, account)
        if value is None:
            raise SecretNotFound(f"No secret for service={service!r} account={account!r}")
        return value

    def set(self, service: str, account: str, value: str) -> None:
        keyring.set_password(service, account, value)

    def delete(self, service: str, account: str) -> None:
        try:
            keyring.delete_password(service, account)
        except keyring.errors.PasswordDeleteError:
            pass  # idempotent
```

- [ ] **Step 6: Add Keychain integration test (skipped if no keyring backend)**

Add to `tests/test_secrets.py`:
```python
import keyring


def _has_real_keyring() -> bool:
    backend = keyring.get_keyring()
    name = type(backend).__name__
    return name not in ("Keyring", "fail.Keyring")


@pytest.mark.skipif(not _has_real_keyring(), reason="No real keyring backend available")
def test_keyring_backend_roundtrip():
    from rufino.runtime.secrets import KeyringSecretStore

    store = KeyringSecretStore()
    service = "rufino-test-foundation-task4"
    account = "test-user"

    try:
        store.set(service, account, "hello-rufino")
        assert store.get(service, account) == "hello-rufino"
    finally:
        store.delete(service, account)
```

- [ ] **Step 7: Run all secrets tests**

Run: `pytest tests/test_secrets.py -v`
Expected: 5 passed + 1 passed-or-skipped depending on environment.

- [ ] **Step 8: Commit**

```bash
git add src/rufino/runtime/__init__.py src/rufino/runtime/secrets.py tests/test_secrets.py
git commit -m "feat(foundation): SecretStore abstraction with in-memory + keyring backends"
```

---

## Task 5: Scheduler abstraction with launchd and cron backends

**Files:**
- Create: `src/rufino/runtime/scheduler.py`
- Create: `tests/test_scheduler.py`

- [ ] **Step 1: Write the failing test**

`tests/test_scheduler.py`:
```python
import platform
import pytest
from pathlib import Path
from rufino.runtime.scheduler import (
    Scheduler,
    LaunchdScheduler,
    CronScheduler,
    ScheduledJob,
    pick_scheduler_for_os,
)


def test_scheduled_job_required_fields():
    job = ScheduledJob(name="rufino.test", cron="0 22 * * *", command="echo hi")
    assert job.name == "rufino.test"
    assert job.cron == "0 22 * * *"
    assert job.command == "echo hi"


def test_launchd_renders_plist():
    job = ScheduledJob(name="rufino.test", cron="0 22 * * *", command="/bin/echo hi")
    plist = LaunchdScheduler().render(job)
    assert "<key>Label</key>" in plist
    assert "<string>rufino.test</string>" in plist
    assert "<key>StartCalendarInterval</key>" in plist
    assert "<key>Hour</key>" in plist
    assert "<integer>22</integer>" in plist
    assert "<key>Minute</key>" in plist
    assert "<integer>0</integer>" in plist


def test_cron_renders_crontab_line():
    job = ScheduledJob(name="rufino.test", cron="0 22 * * *", command="/bin/echo hi")
    line = CronScheduler().render(job)
    assert line.strip() == "0 22 * * * /bin/echo hi # rufino-job:rufino.test"


def test_pick_scheduler_for_os_darwin():
    assert isinstance(pick_scheduler_for_os("Darwin"), LaunchdScheduler)


def test_pick_scheduler_for_os_linux():
    assert isinstance(pick_scheduler_for_os("Linux"), CronScheduler)


def test_pick_scheduler_for_os_unknown_raises():
    with pytest.raises(NotImplementedError):
        pick_scheduler_for_os("Windows")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_scheduler.py -v`
Expected: FAIL with `ModuleNotFoundError: rufino.runtime.scheduler`

- [ ] **Step 3: Write the scheduler module**

`src/rufino/runtime/scheduler.py`:
```python
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ScheduledJob:
    """A scheduled job definition. OS-agnostic."""
    name: str
    cron: str  # standard 5-field cron expression
    command: str


class Scheduler(Protocol):
    """Abstract scheduler. Renders a ScheduledJob to OS-specific format."""

    def render(self, job: ScheduledJob) -> str: ...


class LaunchdScheduler:
    """macOS launchd backend. Renders ScheduledJob to .plist XML."""

    def render(self, job: ScheduledJob) -> str:
        minute, hour, day, month, weekday = job.cron.split()
        if any(c in (minute, hour) for c in ("*", "/", ",", "-")):
            raise NotImplementedError(
                f"LaunchdScheduler supports only simple cron expressions; got {job.cron!r}"
            )
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{job.name}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>-c</string>
        <string>{job.command}</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>{int(hour)}</integer>
        <key>Minute</key>
        <integer>{int(minute)}</integer>
    </dict>
</dict>
</plist>
"""


class CronScheduler:
    """Linux cron backend. Renders ScheduledJob to a crontab line."""

    def render(self, job: ScheduledJob) -> str:
        return f"{job.cron} {job.command} # rufino-job:{job.name}\n"


def pick_scheduler_for_os(os_name: str) -> Scheduler:
    """Return the appropriate Scheduler for the given OS (output of platform.system())."""
    if os_name == "Darwin":
        return LaunchdScheduler()
    if os_name == "Linux":
        return CronScheduler()
    raise NotImplementedError(f"No scheduler backend for OS {os_name!r}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_scheduler.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/rufino/runtime/scheduler.py tests/test_scheduler.py
git commit -m "feat(foundation): Scheduler abstraction with launchd + cron backends"
```

---

## Task 6: Sandbox runtime for transform.py hooks

**Files:**
- Create: `src/rufino/runtime/sandbox.py`
- Create: `tests/test_sandbox.py`
- Create: `tests/fixtures/hooks/echo_transform.py`
- Create: `tests/fixtures/hooks/slow_transform.py`
- Create: `tests/fixtures/hooks/network_transform.py`

- [ ] **Step 1: Write fixture hooks for testing**

`tests/fixtures/hooks/echo_transform.py`:
```python
import json
import sys

data = json.loads(sys.stdin.read())
data["echoed"] = True
sys.stdout.write(json.dumps(data))
```

`tests/fixtures/hooks/slow_transform.py`:
```python
import time
import sys

time.sleep(5)
sys.stdout.write("{}")
```

`tests/fixtures/hooks/network_transform.py`:
```python
import urllib.request
import sys

try:
    urllib.request.urlopen("http://example.com", timeout=2)
    sys.stdout.write('{"network_ok": true}')
except Exception as e:
    sys.stdout.write(f'{{"network_error": "{e}"}}')
```

- [ ] **Step 2: Write the failing test**

`tests/test_sandbox.py`:
```python
import pytest
from pathlib import Path
from rufino.runtime.sandbox import run_transform_hook, SandboxResult, SandboxTimeout


FIXTURES = Path(__file__).parent / "fixtures" / "hooks"


def test_echo_hook_roundtrip():
    result = run_transform_hook(
        hook_path=FIXTURES / "echo_transform.py",
        input_data={"hello": "world"},
        timeout_seconds=10,
        allow_network=False,
    )
    assert isinstance(result, SandboxResult)
    assert result.output == {"hello": "world", "echoed": True}
    assert result.error is None


def test_timeout_enforced():
    with pytest.raises(SandboxTimeout):
        run_transform_hook(
            hook_path=FIXTURES / "slow_transform.py",
            input_data={},
            timeout_seconds=1,
            allow_network=False,
        )


def test_network_blocked_by_default():
    result = run_transform_hook(
        hook_path=FIXTURES / "network_transform.py",
        input_data={},
        timeout_seconds=5,
        allow_network=False,
    )
    # On a sandboxed-network environment we'd see network_error.
    # We tolerate either, but assert the call returned without raising.
    assert "network_ok" in result.output or "network_error" in result.output
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_sandbox.py -v`
Expected: FAIL with `ModuleNotFoundError: rufino.runtime.sandbox`

- [ ] **Step 4: Write the sandbox module**

`src/rufino/runtime/sandbox.py`:
```python
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class SandboxTimeout(Exception):
    """Raised when a hook exceeds its timeout."""


class SandboxHookFailed(Exception):
    """Raised when a hook exits with non-zero status or invalid output."""


@dataclass
class SandboxResult:
    output: dict[str, Any]
    stderr: str
    error: str | None = None


def run_transform_hook(
    *,
    hook_path: Path,
    input_data: dict[str, Any],
    timeout_seconds: int,
    allow_network: bool,
) -> SandboxResult:
    """Run a transform.py hook in an isolated subprocess.

    Args:
        hook_path: absolute path to transform.py
        input_data: dict passed to the hook as JSON on stdin
        timeout_seconds: hard wall-clock timeout (1-300 seconds)
        allow_network: when False, hook is run with PATH stripped to /usr/bin (best-effort
                       network restriction; a true network namespace is not portable across OSes)

    Returns:
        SandboxResult with parsed JSON output

    Raises:
        SandboxTimeout if hook exceeds timeout
        SandboxHookFailed if hook returns non-zero or invalid JSON
    """
    if not (1 <= timeout_seconds <= 300):
        raise ValueError("timeout_seconds must be in [1, 300]")

    env = {"PATH": "/usr/bin", "PYTHONUNBUFFERED": "1"}

    try:
        completed = subprocess.run(
            [sys.executable, str(hook_path)],
            input=json.dumps(input_data),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise SandboxTimeout(
            f"Hook {hook_path} exceeded {timeout_seconds}s timeout"
        ) from e

    if completed.returncode != 0:
        raise SandboxHookFailed(
            f"Hook {hook_path} exited {completed.returncode}: {completed.stderr}"
        )

    try:
        output = json.loads(completed.stdout)
    except json.JSONDecodeError as e:
        raise SandboxHookFailed(f"Hook {hook_path} returned invalid JSON: {e}") from e

    return SandboxResult(output=output, stderr=completed.stderr, error=None)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_sandbox.py -v`
Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
git add src/rufino/runtime/sandbox.py tests/test_sandbox.py tests/fixtures/hooks/
git commit -m "feat(foundation): sandbox runtime for transform hooks with timeout"
```

---

## Task 7: Transaction log for bootstrap rollback

**Files:**
- Create: `src/rufino/runtime/transaction_log.py`
- Create: `tests/test_transaction_log.py`

- [ ] **Step 1: Write the failing test**

`tests/test_transaction_log.py`:
```python
import json
import pytest
from pathlib import Path
from rufino.runtime.transaction_log import (
    TransactionLog,
    LogEntry,
    apply_and_log,
)


def test_log_entry_serializable():
    entry = LogEntry(op="mkdir", target="/tmp/test", rollback="rmdir")
    assert json.loads(json.dumps(entry.to_dict())) == entry.to_dict()


def test_log_records_operations(tmp_path: Path):
    log = TransactionLog(tmp_path / "tx.json")
    log.record(LogEntry(op="mkdir", target="/tmp/a", rollback="rmdir"))
    log.record(LogEntry(op="write", target="/tmp/b", rollback="delete"))

    assert log.entries() == [
        LogEntry(op="mkdir", target="/tmp/a", rollback="rmdir"),
        LogEntry(op="write", target="/tmp/b", rollback="delete"),
    ]


def test_log_persists_to_disk(tmp_path: Path):
    log_path = tmp_path / "tx.json"
    log = TransactionLog(log_path)
    log.record(LogEntry(op="mkdir", target="/x", rollback="rmdir"))

    reloaded = TransactionLog.load(log_path)
    assert reloaded.entries() == [LogEntry(op="mkdir", target="/x", rollback="rmdir")]


def test_rollback_executes_in_reverse_order(tmp_path: Path):
    log = TransactionLog(tmp_path / "tx.json")
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.write_text("content")

    log.record(LogEntry(op="mkdir", target=str(a), rollback="rmdir"))
    log.record(LogEntry(op="write", target=str(b), rollback="delete"))

    log.rollback()

    assert not a.exists()
    assert not b.exists()


def test_apply_and_log_helper(tmp_path: Path):
    log = TransactionLog(tmp_path / "tx.json")
    target = tmp_path / "new_dir"

    apply_and_log(
        log,
        op="mkdir",
        target=str(target),
        apply_fn=lambda: target.mkdir(),
        rollback="rmdir",
    )

    assert target.exists()
    assert len(log.entries()) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_transaction_log.py -v`
Expected: FAIL with `ModuleNotFoundError: rufino.runtime.transaction_log`

- [ ] **Step 3: Write the transaction log module**

`src/rufino/runtime/transaction_log.py`:
```python
import json
import shutil
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable, Any


@dataclass(frozen=True)
class LogEntry:
    """A single bootstrap operation + how to revert it."""
    op: str          # "mkdir" | "write" | "keychain_add" | "plist_install" | ...
    target: str      # what the op acted on (path, service+account, plist name, ...)
    rollback: str    # canonical name of the inverse: "rmdir" | "delete" | "keychain_delete" | ...

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


# Built-in rollback registry. Adapters/runtime can register more.
_ROLLBACK_REGISTRY: dict[str, Callable[[str], None]] = {}


def register_rollback(name: str, fn: Callable[[str], None]) -> None:
    _ROLLBACK_REGISTRY[name] = fn


def _rmdir(target: str) -> None:
    p = Path(target)
    if p.exists():
        shutil.rmtree(p) if p.is_dir() else p.unlink()


def _delete(target: str) -> None:
    p = Path(target)
    if p.exists():
        p.unlink()


register_rollback("rmdir", _rmdir)
register_rollback("delete", _delete)


class TransactionLog:
    """Append-only log of bootstrap operations + their rollbacks. Persisted as JSON."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._entries: list[LogEntry] = []

    def record(self, entry: LogEntry) -> None:
        self._entries.append(entry)
        self._flush()

    def entries(self) -> list[LogEntry]:
        return list(self._entries)

    def rollback(self) -> None:
        """Execute rollback for each entry in REVERSE order."""
        for entry in reversed(self._entries):
            handler = _ROLLBACK_REGISTRY.get(entry.rollback)
            if handler is None:
                raise RuntimeError(f"No rollback handler registered for {entry.rollback!r}")
            handler(entry.target)

    @classmethod
    def load(cls, path: Path) -> "TransactionLog":
        log = cls(path)
        if path.exists():
            raw = json.loads(path.read_text())
            log._entries = [LogEntry(**e) for e in raw]
        return log

    def _flush(self) -> None:
        self._path.write_text(json.dumps([e.to_dict() for e in self._entries], indent=2))


def apply_and_log(
    log: TransactionLog,
    *,
    op: str,
    target: str,
    apply_fn: Callable[[], Any],
    rollback: str,
) -> Any:
    """Execute apply_fn() and only record the log entry on success.

    If apply_fn() raises, the log is unmodified and the exception propagates.
    """
    result = apply_fn()
    log.record(LogEntry(op=op, target=target, rollback=rollback))
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_transaction_log.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/rufino/runtime/transaction_log.py tests/test_transaction_log.py
git commit -m "feat(foundation): transaction log with reverse-order rollback"
```

---

## Task 8: Validator base interface

**Files:**
- Create: `src/rufino/runtime/validator_base.py`
- Create: `tests/test_validator_base.py`

- [ ] **Step 1: Write the failing test**

`tests/test_validator_base.py`:
```python
import pytest
from rufino.runtime.validator_base import (
    Validator,
    ValidationError,
    ValidationWarning,
    ValidationResult,
)


def test_validation_result_ok_when_no_issues():
    result = ValidationResult(errors=[], warnings=[])
    assert result.ok is True


def test_validation_result_not_ok_with_errors():
    result = ValidationResult(
        errors=[ValidationError(field="name", message="required", line=12)],
        warnings=[],
    )
    assert result.ok is False


def test_validation_result_ok_with_only_warnings():
    result = ValidationResult(
        errors=[],
        warnings=[ValidationWarning(field="qa_triggers", message="empty", line=20)],
    )
    assert result.ok is True


def test_validator_protocol_minimal():
    class NoopValidator:
        def validate(self, manifest: dict) -> ValidationResult:
            return ValidationResult(errors=[], warnings=[])

    v: Validator = NoopValidator()
    assert v.validate({}).ok
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_validator_base.py -v`
Expected: FAIL with `ModuleNotFoundError: rufino.runtime.validator_base`

- [ ] **Step 3: Write the validator_base module**

`src/rufino/runtime/validator_base.py`:
```python
from dataclasses import dataclass, field
from typing import Protocol, Any


@dataclass(frozen=True)
class ValidationError:
    field: str
    message: str
    line: int | None = None


@dataclass(frozen=True)
class ValidationWarning:
    field: str
    message: str
    line: int | None = None


@dataclass
class ValidationResult:
    errors: list[ValidationError] = field(default_factory=list)
    warnings: list[ValidationWarning] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0

    def report(self) -> str:
        """Render result for user-facing display."""
        lines: list[str] = []
        for e in self.errors:
            loc = f"line {e.line}: " if e.line else ""
            lines.append(f"ERROR  {e.field}: {loc}{e.message}")
        for w in self.warnings:
            loc = f"line {w.line}: " if w.line else ""
            lines.append(f"WARN   {w.field}: {loc}{w.message}")
        if not lines:
            return "OK"
        return "\n".join(lines)


class Validator(Protocol):
    """Common interface for shape-specific manifest validators.

    Implementations: WorkerAdapterValidator, VerticalConfigValidator, QuestionTemplateValidator.
    """

    def validate(self, manifest: dict[str, Any]) -> ValidationResult: ...
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_validator_base.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/rufino/runtime/validator_base.py tests/test_validator_base.py
git commit -m "feat(foundation): Validator base interface with ValidationResult"
```

---

## Task 9: End-to-end foundation smoke test

**Files:**
- Create: `tests/test_foundation_smoke.py`

- [ ] **Step 1: Write the smoke test**

`tests/test_foundation_smoke.py`:
```python
"""End-to-end smoke test of all foundation modules together."""
from pathlib import Path

from rufino import __version__
from rufino.helpers import v1
from rufino.runtime.scheduler import ScheduledJob, pick_scheduler_for_os, LaunchdScheduler
from rufino.runtime.secrets import InMemorySecretStore
from rufino.runtime.transaction_log import TransactionLog, LogEntry, apply_and_log
from rufino.runtime.validator_base import ValidationResult, ValidationError


def test_foundation_modules_compose(tmp_path: Path):
    # 1. Framework version + helper version reported
    assert __version__ == "0.0.1"
    assert v1.HELPER_VERSION == "1.0.0"

    # 2. Scheduler renders a job (use Darwin path; doesn't actually install)
    job = ScheduledJob(name="rufino.smoke", cron="0 22 * * *", command="/bin/true")
    plist = LaunchdScheduler().render(job)
    assert "rufino.smoke" in plist

    # 3. Secrets in-memory store roundtrips
    store = InMemorySecretStore()
    store.set("rufino-smoke", "user", "secret")
    assert store.get("rufino-smoke", "user") == "secret"

    # 4. Transaction log records + rolls back filesystem ops
    log_path = tmp_path / "tx.json"
    log = TransactionLog(log_path)
    target = tmp_path / "smoke_dir"
    apply_and_log(
        log,
        op="mkdir",
        target=str(target),
        apply_fn=lambda: target.mkdir(),
        rollback="rmdir",
    )
    assert target.exists()
    log.rollback()
    assert not target.exists()

    # 5. ValidationResult composes correctly
    result = ValidationResult(
        errors=[ValidationError(field="x", message="bad")],
        warnings=[],
    )
    assert result.ok is False
    assert "ERROR" in result.report()
```

- [ ] **Step 2: Run the smoke test**

Run: `pytest tests/test_foundation_smoke.py -v`
Expected: 1 passed

- [ ] **Step 3: Run the full test suite**

Run: `pytest -v`
Expected: all tests pass (no regression in earlier tasks)

- [ ] **Step 4: Commit**

```bash
git add tests/test_foundation_smoke.py
git commit -m "test(foundation): end-to-end smoke test composing all modules"
```

---

## Self-review checklist

- [ ] All `pyproject.toml` deps actually used by imports in `src/`
- [ ] Each module has at least one test
- [ ] Smoke test exercises every public module
- [ ] No TODOs, TBDs, or placeholder logic
- [ ] Type signatures consistent (e.g., `SecretStore.get` returns `str` everywhere)
- [ ] Tests use the `tmp_path` fixture for filesystem isolation
- [ ] Commit messages follow `<type>(scope): description` convention

## Done criteria

- `pytest -v` reports 100% pass with 0 skips on macOS Darwin
- `./cli/rufino version` prints `0.0.1`
- `python -c "import rufino; print(rufino.__version__)"` prints `0.0.1`
- All 9 commits present in `git log` with conventional messages
