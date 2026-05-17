import logging
from dataclasses import dataclass
from pathlib import Path

from rufino.engine.output.manifest import parse_output_manifest
from rufino.engine.output.renderer import render_template
from rufino.engine.output.channels.base import Channel


_log = logging.getLogger(__name__)


class UnknownChannelError(Exception):
    """Raised when the manifest references a channel that is not registered."""


class TemplatePathError(Exception):
    """Raised when the manifest template path resolves outside adapter_dir."""


@dataclass
class OutputResult:
    adapter_name: str
    deliveries: int
    errors: list[str]


def dispatch_output(
    *,
    adapter_dir: Path,
    query,
    channels: dict[str, Channel],
    event_context: dict,
) -> OutputResult:
    """Run an Output adapter: queries → render template → deliver to each channel."""
    manifest = parse_output_manifest((adapter_dir / "manifest.yaml").read_text())

    template_path = (adapter_dir / manifest.template).resolve()
    root = adapter_dir.resolve()
    if root != template_path and root not in template_path.parents:
        raise TemplatePathError(
            f"template path escapes adapter_dir: {manifest.template!r}"
        )

    try:
        template_text = template_path.read_text()
        results: dict[str, list[str]] = {}
        for q in manifest.query:
            results[q["name"]] = query.run(q["expression"])
        content = render_template(
            template=template_text, query=results, event=event_context
        )
    except Exception as e:
        _log.exception("Template render failed for adapter %s", manifest.adapter_name)
        return OutputResult(
            adapter_name=manifest.adapter_name,
            deliveries=0,
            errors=[f"render: {e}"],
        )

    deliveries = 0
    errors: list[str] = []
    for delivery in manifest.delivery:
        channel_name = delivery["channel"]
        if channel_name not in channels:
            # Don't short-circuit: record and continue so other deliveries run.
            errors.append(
                f"{channel_name}: channel not registered (unknown channel)"
            )
            continue
        try:
            channels[channel_name].deliver(config=dict(delivery), content=content)
            deliveries += 1
        except Exception as e:
            _log.exception("Channel %s delivery failed", channel_name)
            errors.append(f"{channel_name}: {e}")

    return OutputResult(
        adapter_name=manifest.adapter_name,
        deliveries=deliveries,
        errors=errors,
    )
