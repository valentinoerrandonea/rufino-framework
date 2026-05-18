from dataclasses import dataclass
from pathlib import PurePath
from types import MappingProxyType
from typing import Any, Mapping
import yaml


class ManifestParseError(Exception):
    """Raised when worker adapter manifest is invalid."""


VALID_MODES = {"full", "light", "lint"}


@dataclass(frozen=True)
class WorkerAdapterManifest:
    adapter_name: str
    note_type: str
    applies_when: Mapping[str, Any]
    llm: str
    mode_default: str
    output_schema: Mapping[str, Any]
    triple_vocabulary: tuple[str, ...]
    tag_axes: tuple[Mapping[str, Any], ...]
    destination_path: str
    qa_triggers: tuple[Mapping[str, Any], ...]
    context_injectors: tuple[Mapping[str, Any], ...]
    transform_hook: str | None = None
    batch_size: int = 10


_REQUIRED = (
    "adapter_name",
    "note_type",
    "applies_when",
    "llm",
    "mode_default",
    "output_schema",
    "triple_vocabulary",
    "tag_axes",
    "destination_path",
)


def _freeze(value: Any) -> Any:
    """Recursively wrap dicts in MappingProxyType so a parsed manifest is immutable.

    Lists become tuples; non-collection scalars pass through unchanged.
    """
    if isinstance(value, dict):
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(v) for v in value)
    return value


def parse_worker_manifest(yaml_text: str) -> WorkerAdapterManifest:
    try:
        raw = yaml.safe_load(yaml_text)
    except yaml.YAMLError as e:
        raise ManifestParseError(f"Invalid YAML: {e}") from e

    if not isinstance(raw, dict):
        raise ManifestParseError("Manifest root must be a mapping")

    missing = [f for f in _REQUIRED if f not in raw]
    if missing:
        raise ManifestParseError(f"Missing required fields: {missing}")

    if raw["mode_default"] not in VALID_MODES:
        raise ManifestParseError(
            f"mode_default must be one of {VALID_MODES}, got {raw['mode_default']!r}"
        )

    if PurePath(raw["destination_path"]).is_absolute():
        raise ManifestParseError(
            f"destination_path must be relative, got absolute {raw['destination_path']!r}"
        )

    batch_size_raw = raw.get("batch_size", 10)
    if not isinstance(batch_size_raw, int) or isinstance(batch_size_raw, bool):
        raise ManifestParseError(
            f"batch_size must be a positive integer, got {batch_size_raw!r}"
        )
    if batch_size_raw < 1:
        raise ManifestParseError(
            f"batch_size must be >= 1, got {batch_size_raw}"
        )

    return WorkerAdapterManifest(
        adapter_name=raw["adapter_name"],
        note_type=raw["note_type"],
        applies_when=_freeze(raw["applies_when"]),
        llm=raw["llm"],
        mode_default=raw["mode_default"],
        output_schema=_freeze(raw["output_schema"]),
        triple_vocabulary=tuple(raw["triple_vocabulary"]),
        tag_axes=_freeze(raw["tag_axes"]),
        destination_path=raw["destination_path"],
        qa_triggers=_freeze(raw.get("qa_triggers", [])),
        context_injectors=_freeze(raw.get("context_injectors", [])),
        transform_hook=raw.get("transform_hook"),
        batch_size=batch_size_raw,
    )
