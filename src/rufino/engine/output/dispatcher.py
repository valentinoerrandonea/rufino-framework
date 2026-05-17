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
    query,
    channels: dict[str, Channel],
    event_context: dict,
) -> OutputResult:
    """Run an Output adapter: queries → render template → deliver to each channel."""
    manifest = parse_output_manifest((adapter_dir / "manifest.yaml").read_text())

    results: dict[str, list[str]] = {}
    for q in manifest.query:
        results[q["name"]] = query.run(q["expression"])

    template_text = (adapter_dir / manifest.template).read_text()
    content = render_template(template=template_text, query=results, event=event_context)

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
