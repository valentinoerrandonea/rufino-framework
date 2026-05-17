from dataclasses import dataclass
from pathlib import PurePosixPath, PurePath
from types import MappingProxyType
from typing import Any, Mapping
import yaml


class ManifestParseError(Exception):
    """Raised when output adapter manifest is invalid."""


VALID_TRIGGER_TYPES = {"cron", "on_event"}


@dataclass(frozen=True)
class OutputAdapterManifest:
    adapter_name: str
    trigger_type: str
    query: tuple[Mapping[str, Any], ...]
    template: str
    delivery: tuple[Mapping[str, Any], ...]
    cron_expression: str | None = None
    event_name: str | None = None
    event_filter: str | None = None


def _freeze(value: Any) -> Any:
    """Recursively wrap dicts in MappingProxyType so a parsed manifest is immutable."""
    if isinstance(value, dict):
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(v) for v in value)
    return value


def _validate_relative(path_str: str, field: str) -> None:
    """Reject absolute or parent-escaping paths in manifest fields."""
    if PurePath(path_str).is_absolute() or PurePosixPath(path_str).is_absolute():
        raise ManifestParseError(f"{field} must be relative, got {path_str!r}")
    parts = PurePosixPath(path_str).parts
    if ".." in parts:
        raise ManifestParseError(f"{field} must not contain '..', got {path_str!r}")


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

    if not isinstance(raw["template"], str):
        raise ManifestParseError("template must be a string")
    _validate_relative(raw["template"], "template")

    if not isinstance(raw["delivery"], list):
        raise ManifestParseError("delivery must be a list")
    for i, d in enumerate(raw["delivery"]):
        if not isinstance(d, dict) or "channel" not in d:
            raise ManifestParseError(f"delivery[{i}] must be a mapping with 'channel'")
        if d["channel"] == "file":
            if "path" not in d or not isinstance(d["path"], str):
                raise ManifestParseError(f"delivery[{i}].path required for file channel")
            _validate_relative(d["path"], f"delivery[{i}].path")

    common = dict(
        adapter_name=raw["adapter_name"],
        trigger_type=trig["type"],
        query=_freeze(raw["query"]),
        template=raw["template"],
        delivery=_freeze(raw["delivery"]),
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
