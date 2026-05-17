import pytest
from pathlib import Path
from rufino.engine.output.dispatcher import (
    dispatch_output,
    OutputResult,
    TemplatePathError,
)
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


def test_unknown_channel_in_manifest_appends_to_errors(tmp_vault: Path):
    """Unknown channel must not short-circuit the loop — record as error
    so other deliveries in the same manifest can succeed."""
    query = StubQueryLayer()
    channels: dict = {}

    result = dispatch_output(
        adapter_dir=FIXTURE,
        query=query,
        channels=channels,
        event_context={},
    )
    assert result.deliveries == 0
    assert any("file" in e for e in result.errors)
    assert any("not registered" in e.lower() or "unknown" in e.lower() for e in result.errors)


class _FailingChannel:
    def deliver(self, *, config, content):
        raise RuntimeError("boom")


def test_channel_delivery_failure_is_collected(tmp_vault: Path, caplog):
    query = StubQueryLayer()
    channels = {"file": _FailingChannel()}

    import logging
    with caplog.at_level(logging.ERROR):
        result = dispatch_output(
            adapter_dir=FIXTURE,
            query=query,
            channels=channels,
            event_context={},
        )

    assert result.deliveries == 0
    assert len(result.errors) == 1
    assert "boom" in result.errors[0]
    assert any("delivery failed" in r.message for r in caplog.records)


def test_render_failure_returns_errors_not_raises(tmp_path: Path):
    """A jinja UndefinedError must end up in result.errors, not crash the dispatcher."""
    adapter = tmp_path / "adapter"
    adapter.mkdir()
    (adapter / "manifest.yaml").write_text(
        'adapter_name: bad-template\n'
        'trigger: { type: cron, expression: "0 * * * *" }\n'
        'query: []\n'
        'template: "./t.md"\n'
        'delivery: []\n'
    )
    (adapter / "t.md").write_text("hola {{ event.does_not_exist }}")

    result = dispatch_output(
        adapter_dir=adapter,
        query=StubQueryLayer(),
        channels={},
        event_context={},
    )
    assert result.deliveries == 0
    assert len(result.errors) == 1
    assert result.errors[0].startswith("render:")


def test_template_outside_adapter_dir_raises(tmp_path: Path):
    # Build a fake adapter that points template at /etc/passwd
    adapter = tmp_path / "evil-adapter"
    adapter.mkdir()
    (adapter / "manifest.yaml").write_text(
        'adapter_name: evil\n'
        'trigger: { type: cron, expression: "* * * * *" }\n'
        'query: []\n'
        'template: "./safe.md"\n'
        'delivery: []\n'
    )
    # Create a real-looking template, but then symlink it to escape
    safe = adapter / "safe.md"
    safe.write_text("ok")
    safe.unlink()
    safe.symlink_to(tmp_path / "outside.md")
    (tmp_path / "outside.md").write_text("leaked")

    with pytest.raises(TemplatePathError):
        dispatch_output(
            adapter_dir=adapter,
            query=StubQueryLayer(),
            channels={},
            event_context={},
        )
