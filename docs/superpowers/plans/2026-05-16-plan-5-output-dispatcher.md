# Plan 5 — Output dispatcher primitive Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementar la primitive Output: el worker adapter shape para outputs (cron + on_event triggers), channels built-in (`file://`, `email://`, `webhook://`, `push://`), templating con jinja2 + query helper. Adapter ejemplo `output-digest-semanal-facultad` que cada viernes 18:00 lee notas de la última semana del vault y escribe un digest a un file + envía por email.

**Architecture:** Output dispatcher recibe un manifest, evalúa el trigger (cron → ejecuta si el cron expression matchea ahora, on_event → ejecuta si el evento recibido matchea el filter), corre las queries declaradas via Query layer stub, renderiza el template con los resultados, y envía a cada delivery channel. Channels son adapters con un protocolo común.

**Tech Stack:** Python 3.11+, jinja2, smtplib (stdlib, email channel), pyyaml.

**Dependencias previas:** Plan 1 (Foundation), Plan 3 (Process — comparte StubQueryLayer; reutilizable).

**Plans que dependen de este:** Plan 8 (Wizard — genera adapters de Output).

---

## File Structure

```
src/rufino/engine/output/
├── __init__.py
├── manifest.py             # OutputAdapterManifest + parser
├── validator.py            # OutputAdapterValidator
├── dispatcher.py           # output(adapter_dir, trigger_context) entry
├── channels/
│   ├── __init__.py
│   ├── base.py             # Channel protocol
│   ├── file_channel.py     # writes to a vault path
│   ├── email_channel.py    # SMTP via Keychain-stored credentials
│   ├── webhook_channel.py  # POST JSON to URL
│   └── push_channel.py     # macOS notification (osascript) / Linux (notify-send)
└── renderer.py             # jinja2 wrapper
src/rufino/cli.py           # MODIFY: `rufino output <adapter_dir>`
tests/test_output_*.py
tests/fixtures/adapters/output-digest-semanal-facultad/
├── manifest.yaml
└── templates/
    └── digest.md
```

---

## Task 1: Output manifest parser

**Files:**
- Create: `src/rufino/engine/output/__init__.py`
- Create: `src/rufino/engine/output/manifest.py`
- Create: `tests/test_output_manifest.py`

- [ ] **Step 1: Failing test**

`tests/test_output_manifest.py`:
```python
import pytest
from rufino.engine.output.manifest import (
    OutputAdapterManifest,
    parse_output_manifest,
    ManifestParseError,
)


CRON_YAML = """
adapter_name: digest-semanal-facultad
trigger:
  type: cron
  expression: "0 18 * * 5"
query:
  - { name: notas_semana, expression: "created >= 7 days ago" }
template: ./templates/digest.md
delivery:
  - { channel: file, path: "general/digests/<YYYY-WW>.md" }
  - { channel: email, to: "user@example.com", subject: "Digest" }
"""

ON_EVENT_YAML = """
adapter_name: meeting-prep
trigger:
  type: on_event
  event: calendar_event
  filter: "tag = '1:1' AND starts_in_hours < 24"
query:
  - { name: notas, expression: "tag = persona/<event.attendee>" }
template: ./templates/prep.md
delivery:
  - { channel: file, path: "meetings/<event.attendee>/<YYYY-MM-DD>-1on1.md" }
"""


def test_parses_cron_trigger():
    m = parse_output_manifest(CRON_YAML)
    assert m.trigger_type == "cron"
    assert m.cron_expression == "0 18 * * 5"
    assert len(m.delivery) == 2


def test_parses_on_event_trigger():
    m = parse_output_manifest(ON_EVENT_YAML)
    assert m.trigger_type == "on_event"
    assert m.event_name == "calendar_event"
    assert "1:1" in m.event_filter


def test_invalid_trigger_type_raises():
    yaml = CRON_YAML.replace("type: cron", "type: bogus")
    with pytest.raises(ManifestParseError, match="trigger.type"):
        parse_output_manifest(yaml)


def test_missing_template_raises():
    yaml = CRON_YAML.replace("template: ./templates/digest.md\n", "")
    with pytest.raises(ManifestParseError, match="template"):
        parse_output_manifest(yaml)
```

- [ ] **Step 2: Run (fails)**

- [ ] **Step 3: Implement**

`src/rufino/engine/output/__init__.py`: `` (empty)

`src/rufino/engine/output/manifest.py`:
```python
from dataclasses import dataclass
from typing import Any
import yaml


class ManifestParseError(Exception):
    """Raised when output adapter manifest is invalid."""


VALID_TRIGGER_TYPES = {"cron", "on_event"}


@dataclass(frozen=True)
class OutputAdapterManifest:
    adapter_name: str
    trigger_type: str
    query: tuple[dict[str, Any], ...]
    template: str
    delivery: tuple[dict[str, Any], ...]
    cron_expression: str | None = None
    event_name: str | None = None
    event_filter: str | None = None


def parse_output_manifest(yaml_text: str) -> OutputAdapterManifest:
    try:
        raw = yaml.safe_load(yaml_text)
    except yaml.YAMLError as e:
        raise ManifestParseError(f"Invalid YAML: {e}") from e

    if not isinstance(raw, dict):
        raise ManifestParseError("Manifest root must be a mapping")

    for f in ("adapter_name", "trigger", "query", "template", "delivery"):
        if f not in raw:
            raise ManifestParseError(f"Missing required field: {f}")

    trig = raw["trigger"]
    if not isinstance(trig, dict) or "type" not in trig:
        raise ManifestParseError("trigger must be a mapping with 'type'")
    if trig["type"] not in VALID_TRIGGER_TYPES:
        raise ManifestParseError(
            f"trigger.type must be in {VALID_TRIGGER_TYPES}, got {trig['type']!r}"
        )

    common = dict(
        adapter_name=raw["adapter_name"],
        trigger_type=trig["type"],
        query=tuple(raw["query"]),
        template=raw["template"],
        delivery=tuple(raw["delivery"]),
    )

    if trig["type"] == "cron":
        if "expression" not in trig:
            raise ManifestParseError("trigger.cron requires 'expression'")
        return OutputAdapterManifest(**common, cron_expression=trig["expression"])

    # on_event
    if "event" not in trig:
        raise ManifestParseError("trigger.on_event requires 'event'")
    return OutputAdapterManifest(
        **common,
        event_name=trig["event"],
        event_filter=trig.get("filter"),
    )
```

- [ ] **Step 4: Run tests** — Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/rufino/engine/output/ tests/test_output_manifest.py
git commit -m "feat(output): manifest parser with cron + on_event triggers"
```

---

## Task 2: Channel protocol + file channel

**Files:**
- Create: `src/rufino/engine/output/channels/__init__.py`
- Create: `src/rufino/engine/output/channels/base.py`
- Create: `src/rufino/engine/output/channels/file_channel.py`
- Create: `tests/test_output_channel_file.py`

- [ ] **Step 1: Failing test**

`tests/test_output_channel_file.py`:
```python
from pathlib import Path
from rufino.engine.output.channels.file_channel import FileChannel
from rufino.engine.output.channels.base import Channel


def test_file_channel_writes_to_vault(tmp_vault: Path):
    ch = FileChannel(vault_root=tmp_vault)
    ch.deliver(
        config={"path": "general/digests/2026-W20.md"},
        content="# Digest\nBody.\n",
    )
    out = tmp_vault / "general" / "digests" / "2026-W20.md"
    assert out.exists()
    assert "Digest" in out.read_text()


def test_file_channel_protocol():
    assert isinstance(FileChannel(vault_root=Path("/x")), Channel)


def test_file_channel_creates_parents(tmp_vault: Path):
    ch = FileChannel(vault_root=tmp_vault)
    ch.deliver(
        config={"path": "deeply/nested/path/out.md"},
        content="content",
    )
    assert (tmp_vault / "deeply" / "nested" / "path" / "out.md").exists()
```

- [ ] **Step 2: Run (fails)**

- [ ] **Step 3: Implement**

`src/rufino/engine/output/channels/__init__.py`: `` (empty)

`src/rufino/engine/output/channels/base.py`:
```python
from typing import Protocol, Any


class Channel(Protocol):
    """Common interface for delivery channels (file, email, webhook, push)."""

    def deliver(self, *, config: dict[str, Any], content: str) -> None: ...
```

`src/rufino/engine/output/channels/file_channel.py`:
```python
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class FileChannel:
    vault_root: Path

    def deliver(self, *, config: dict[str, Any], content: str) -> None:
        path = self.vault_root / config["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
```

- [ ] **Step 4: Run tests** — Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/rufino/engine/output/channels/ tests/test_output_channel_file.py
git commit -m "feat(output): Channel protocol + FileChannel"
```

---

## Task 3: Email channel (SMTP)

**Files:**
- Create: `src/rufino/engine/output/channels/email_channel.py`
- Create: `tests/test_output_channel_email.py`

- [ ] **Step 1: Failing test**

`tests/test_output_channel_email.py`:
```python
from unittest.mock import patch, MagicMock
from rufino.engine.output.channels.email_channel import EmailChannel
from rufino.runtime.secrets import InMemorySecretStore


def test_email_channel_invokes_smtp():
    secrets = InMemorySecretStore()
    secrets.set("rufino-smtp", "user@example.com", "app-password-xyz")

    ch = EmailChannel(
        smtp_host="smtp.gmail.com",
        smtp_port=587,
        from_address="user@example.com",
        secrets=secrets,
    )

    with patch("smtplib.SMTP") as mock_smtp:
        instance = MagicMock()
        mock_smtp.return_value.__enter__.return_value = instance
        ch.deliver(
            config={"to": "dest@example.com", "subject": "Test"},
            content="Body.",
        )
        instance.starttls.assert_called_once()
        instance.login.assert_called_once_with("user@example.com", "app-password-xyz")
        instance.send_message.assert_called_once()
```

- [ ] **Step 2: Run (fails)**

- [ ] **Step 3: Implement**

`src/rufino/engine/output/channels/email_channel.py`:
```python
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Any

from rufino.runtime.secrets import SecretStore


@dataclass
class EmailChannel:
    smtp_host: str
    smtp_port: int
    from_address: str
    secrets: SecretStore

    def deliver(self, *, config: dict[str, Any], content: str) -> None:
        msg = EmailMessage()
        msg["From"] = self.from_address
        msg["To"] = config["to"]
        msg["Subject"] = config["subject"]
        msg.set_content(content)

        password = self.secrets.get("rufino-smtp", self.from_address)

        with smtplib.SMTP(self.smtp_host, self.smtp_port) as s:
            s.starttls()
            s.login(self.from_address, password)
            s.send_message(msg)
```

- [ ] **Step 4: Run tests** — Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add src/rufino/engine/output/channels/email_channel.py tests/test_output_channel_email.py
git commit -m "feat(output): EmailChannel via SMTP with secret store"
```

---

## Task 4: Webhook channel + push channel (stubs)

**Files:**
- Create: `src/rufino/engine/output/channels/webhook_channel.py`
- Create: `src/rufino/engine/output/channels/push_channel.py`
- Create: `tests/test_output_channel_webhook_push.py`

- [ ] **Step 1: Failing test**

`tests/test_output_channel_webhook_push.py`:
```python
from unittest.mock import patch, MagicMock
from rufino.engine.output.channels.webhook_channel import WebhookChannel
from rufino.engine.output.channels.push_channel import PushChannel


def test_webhook_posts_json():
    ch = WebhookChannel()
    with patch("urllib.request.urlopen") as mock_open:
        mock_open.return_value.__enter__.return_value.read.return_value = b""
        ch.deliver(
            config={"url": "https://example.com/hook"},
            content="message body",
        )
        mock_open.assert_called_once()
        req = mock_open.call_args[0][0]
        assert req.full_url == "https://example.com/hook"


def test_push_invokes_osascript_on_darwin():
    ch = PushChannel(platform="Darwin")
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        ch.deliver(
            config={"title": "Rufino"},
            content="Hello",
        )
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "osascript"


def test_push_invokes_notify_send_on_linux():
    ch = PushChannel(platform="Linux")
    with patch("subprocess.run") as mock_run:
        ch.deliver(
            config={"title": "Rufino"},
            content="Hello",
        )
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "notify-send"
```

- [ ] **Step 2: Run (fails)**

- [ ] **Step 3: Implement**

`src/rufino/engine/output/channels/webhook_channel.py`:
```python
import json
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass
class WebhookChannel:
    def deliver(self, *, config: dict[str, Any], content: str) -> None:
        payload = json.dumps({"content": content}).encode("utf-8")
        req = urllib.request.Request(
            url=config["url"],
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as _resp:
            pass  # we don't act on response in v1
```

`src/rufino/engine/output/channels/push_channel.py`:
```python
import subprocess
from dataclasses import dataclass
from typing import Any


@dataclass
class PushChannel:
    platform: str  # "Darwin" or "Linux"

    def deliver(self, *, config: dict[str, Any], content: str) -> None:
        title = config.get("title", "Rufino")
        if self.platform == "Darwin":
            cmd = [
                "osascript", "-e",
                f'display notification "{content}" with title "{title}"',
            ]
        elif self.platform == "Linux":
            cmd = ["notify-send", title, content]
        else:
            raise NotImplementedError(f"No push backend for {self.platform!r}")
        subprocess.run(cmd, check=True)
```

- [ ] **Step 4: Run tests** — Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/rufino/engine/output/channels/webhook_channel.py src/rufino/engine/output/channels/push_channel.py tests/test_output_channel_webhook_push.py
git commit -m "feat(output): WebhookChannel + PushChannel (macOS osascript / Linux notify-send)"
```

---

## Task 5: Template renderer (jinja2)

**Files:**
- Create: `src/rufino/engine/output/renderer.py`
- Create: `tests/test_output_renderer.py`

- [ ] **Step 1: Failing test**

`tests/test_output_renderer.py`:
```python
from rufino.engine.output.renderer import render_template


def test_renders_with_query_results():
    template = """# Digest

## Notas
{% for n in query.notas_semana -%}
- {{ n }}
{% endfor -%}
"""
    output = render_template(
        template=template,
        query={"notas_semana": ["nota1.md", "nota2.md"]},
        event={},
    )
    assert "- nota1.md" in output
    assert "- nota2.md" in output


def test_renders_with_event_context():
    template = "Hola {{ event.attendee }}"
    output = render_template(
        template=template,
        query={},
        event={"attendee": "beto"},
    )
    assert output == "Hola beto"
```

- [ ] **Step 2: Run (fails)**

- [ ] **Step 3: Add jinja2 dependency**

Modify `pyproject.toml`:
```toml
dependencies = [
    "click>=8.1",
    "pyyaml>=6.0",
    "keyring>=24.0",
    "jinja2>=3.1",
]
```

Run: `pip install -e ".[dev]"` to install jinja2.

- [ ] **Step 4: Implement renderer**

`src/rufino/engine/output/renderer.py`:
```python
from jinja2 import Environment, BaseLoader, StrictUndefined


_ENV = Environment(loader=BaseLoader(), undefined=StrictUndefined, autoescape=False)


def render_template(*, template: str, query: dict, event: dict) -> str:
    """Render a jinja2 template with `query.*` and `event.*` available."""
    tmpl = _ENV.from_string(template)
    return tmpl.render(query=query, event=event)
```

- [ ] **Step 5: Run tests** — Expected: 2 passed

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/rufino/engine/output/renderer.py tests/test_output_renderer.py
git commit -m "feat(output): jinja2 template renderer for digests and reports"
```

---

## Task 6: Dispatcher — orchestrates query + render + delivery

**Files:**
- Create: `src/rufino/engine/output/dispatcher.py`
- Create: `tests/fixtures/adapters/output-digest-semanal-facultad/manifest.yaml`
- Create: `tests/fixtures/adapters/output-digest-semanal-facultad/templates/digest.md`
- Create: `tests/test_output_dispatcher.py`

- [ ] **Step 1: Create fixture**

`tests/fixtures/adapters/output-digest-semanal-facultad/manifest.yaml`:
```yaml
adapter_name: digest-semanal-facultad
trigger:
  type: cron
  expression: "0 18 * * 5"
query:
  - { name: notas_semana, expression: "created >= 7 days ago" }
template: ./templates/digest.md
delivery:
  - { channel: file, path: "general/digests/W20.md" }
```

`tests/fixtures/adapters/output-digest-semanal-facultad/templates/digest.md`:
```markdown
# Digest semanal

## Notas de esta semana
{% for n in query.notas_semana -%}
- {{ n }}
{% endfor %}
```

- [ ] **Step 2: Failing test**

`tests/test_output_dispatcher.py`:
```python
from pathlib import Path
from rufino.engine.output.dispatcher import dispatch_output, OutputResult
from rufino.engine.process.context_injectors import StubQueryLayer
from rufino.engine.output.channels.file_channel import FileChannel


FIXTURE = Path(__file__).parent / "fixtures" / "adapters" / "output-digest-semanal-facultad"


def test_cron_trigger_renders_and_writes(tmp_vault: Path):
    query = StubQueryLayer(canned_results={
        "created >= 7 days ago": ["apuntes/ml-i/clase1.md", "apuntes/ml-i/clase2.md"],
    })
    channels = {"file": FileChannel(vault_root=tmp_vault)}

    result = dispatch_output(
        adapter_dir=FIXTURE,
        query=query,
        channels=channels,
        event_context={},
    )

    assert isinstance(result, OutputResult)
    assert result.deliveries == 1
    out = tmp_vault / "general" / "digests" / "W20.md"
    assert out.exists()
    content = out.read_text()
    assert "apuntes/ml-i/clase1.md" in content
    assert "apuntes/ml-i/clase2.md" in content


def test_unknown_channel_in_manifest_raises(tmp_vault: Path):
    query = StubQueryLayer()
    channels = {}  # FileChannel NOT registered

    with pytest.raises(Exception, match="file"):
        dispatch_output(
            adapter_dir=FIXTURE,
            query=query,
            channels=channels,
            event_context={},
        )
```

Add at top of file: `import pytest`

- [ ] **Step 3: Run (fails)**

- [ ] **Step 4: Implement**

`src/rufino/engine/output/dispatcher.py`:
```python
from dataclasses import dataclass
from pathlib import Path

from rufino.engine.output.manifest import parse_output_manifest
from rufino.engine.output.renderer import render_template
from rufino.engine.output.channels.base import Channel


class UnknownChannelError(Exception):
    """Raised when the manifest references a channel that is not registered."""


@dataclass
class OutputResult:
    adapter_name: str
    deliveries: int
    errors: list[str]


def dispatch_output(
    *,
    adapter_dir: Path,
    query,                                    # implements .run(query_string) → list[str]
    channels: dict[str, Channel],
    event_context: dict,
) -> OutputResult:
    """Run an Output adapter: queries → render template → deliver to each channel."""
    manifest = parse_output_manifest((adapter_dir / "manifest.yaml").read_text())

    # 1. Run queries
    results: dict[str, list[str]] = {}
    for q in manifest.query:
        results[q["name"]] = query.run(q["expression"])

    # 2. Render template
    template_text = (adapter_dir / manifest.template).read_text()
    content = render_template(template=template_text, query=results, event=event_context)

    # 3. Deliver to each channel
    deliveries = 0
    errors: list[str] = []
    for delivery in manifest.delivery:
        channel_name = delivery["channel"]
        if channel_name not in channels:
            raise UnknownChannelError(
                f"Manifest references channel {channel_name!r} but it is not registered"
            )
        try:
            channels[channel_name].deliver(config=delivery, content=content)
            deliveries += 1
        except Exception as e:
            errors.append(f"{channel_name}: {e}")

    return OutputResult(
        adapter_name=manifest.adapter_name,
        deliveries=deliveries,
        errors=errors,
    )
```

- [ ] **Step 5: Run tests** — Expected: 2 passed

- [ ] **Step 6: Commit**

```bash
git add src/rufino/engine/output/dispatcher.py tests/fixtures/adapters/output-digest-semanal-facultad/ tests/test_output_dispatcher.py
git commit -m "feat(output): dispatcher orchestrating query → render → channels"
```

---

## Task 7: CLI command `rufino output <adapter_dir>`

**Files:**
- Modify: `src/rufino/cli.py`
- Create: `tests/test_cli_output.py`

- [ ] **Step 1: Failing test**

`tests/test_cli_output.py`:
```python
from pathlib import Path
from click.testing import CliRunner
from rufino.cli import cli


FIXTURE = Path(__file__).parent / "fixtures" / "adapters" / "output-digest-semanal-facultad"


def test_output_cli_runs_adapter(tmp_vault: Path):
    runner = CliRunner()
    result = runner.invoke(cli, [
        "output", str(FIXTURE),
        "--vault", str(tmp_vault),
    ])
    assert result.exit_code == 0, result.output
    out = tmp_vault / "general" / "digests" / "W20.md"
    assert out.exists()
```

- [ ] **Step 2: Run (fails)**

- [ ] **Step 3: Append to `src/rufino/cli.py`**

```python
from rufino.engine.output.dispatcher import dispatch_output
from rufino.engine.output.channels.file_channel import FileChannel
from rufino.engine.process.context_injectors import StubQueryLayer


@cli.command(name="output")
@click.argument("adapter_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--vault", "vault_root", required=True, type=click.Path(path_type=Path))
def output_cmd(adapter_dir: Path, vault_root: Path) -> None:
    """Run an Output adapter once (uses stub Query layer in v1)."""
    channels = {"file": FileChannel(vault_root=vault_root)}
    # Email/webhook/push wired in plan 7+ with real config
    result = dispatch_output(
        adapter_dir=adapter_dir,
        query=StubQueryLayer(),
        channels=channels,
        event_context={},
    )
    click.echo(
        f"adapter={result.adapter_name} deliveries={result.deliveries} "
        f"errors={len(result.errors)}"
    )
```

- [ ] **Step 4: Run tests** — Expected: 1 passed

- [ ] **Step 5: Run full suite**

Run: `pytest -v` — all pass

- [ ] **Step 6: Commit**

```bash
git add src/rufino/cli.py tests/test_cli_output.py
git commit -m "feat(output): CLI command 'rufino output' (file channel + stub Query)"
```

---

## Self-review checklist

- [ ] Manifest parser distinguishes cron vs on_event triggers
- [ ] Channel protocol is satisfied by all 4 implementations
- [ ] FileChannel creates parent directories automatically
- [ ] EmailChannel reads password from SecretStore (not env var)
- [ ] Webhook posts JSON with `Content-Type: application/json`
- [ ] PushChannel raises clear error on unsupported platform
- [ ] Renderer uses StrictUndefined (fails fast on missing variable)
- [ ] Dispatcher raises UnknownChannelError when manifest references unregistered channel

## Done criteria

- `pytest tests/test_output_*.py -v` all pass
- `./cli/rufino output tests/fixtures/adapters/output-digest-semanal-facultad --vault X` exits 0 and writes the digest file
