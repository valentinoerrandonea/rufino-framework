from dataclasses import dataclass
from pathlib import PurePath
import yaml


class ManifestParseError(Exception):
    """Raised when manifest YAML is invalid or missing required fields."""


@dataclass(frozen=True)
class MemoryLoopManifest:
    adapter_name: str
    vertical_name: str
    entity_types: tuple[str, ...]
    note_destinations: dict[str, str]
    rule_extensions: tuple[str, ...]


_REQUIRED_FIELDS = ("adapter_name", "vertical_name", "entity_types", "note_destinations")


def parse_manifest(yaml_text: str) -> MemoryLoopManifest:
    try:
        raw = yaml.safe_load(yaml_text)
    except yaml.YAMLError as e:
        raise ManifestParseError(f"Invalid YAML: {e}") from e

    if not isinstance(raw, dict):
        raise ManifestParseError("Manifest root must be a mapping")

    missing = [f for f in _REQUIRED_FIELDS if f not in raw]
    if missing:
        raise ManifestParseError(f"Missing required fields: {missing}")

    entity_types = raw["entity_types"]
    if not isinstance(entity_types, list) or len(entity_types) == 0:
        raise ManifestParseError("entity_types must be a non-empty list")

    destinations = raw["note_destinations"]
    if not isinstance(destinations, dict):
        raise ManifestParseError("note_destinations must be a mapping")

    for entity, path in destinations.items():
        if PurePath(path).is_absolute():
            raise ManifestParseError(
                f"note_destinations[{entity!r}] must be relative, got absolute path {path!r}"
            )

    return MemoryLoopManifest(
        adapter_name=raw["adapter_name"],
        vertical_name=raw["vertical_name"],
        entity_types=tuple(entity_types),
        note_destinations=dict(destinations),
        rule_extensions=tuple(raw.get("rule_extensions", [])),
    )
