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

    if "event" not in trig:
        raise ManifestParseError("trigger.on_event requires 'event'")
    return OutputAdapterManifest(
        **common,
        event_name=trig["event"],
        event_filter=trig.get("filter"),
    )
