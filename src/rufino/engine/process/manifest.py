from dataclasses import dataclass
from pathlib import PurePath
from typing import Any
import yaml


class ManifestParseError(Exception):
    """Raised when worker adapter manifest is invalid."""


VALID_MODES = {"full", "light", "lint"}


@dataclass(frozen=True)
class WorkerAdapterManifest:
    adapter_name: str
    note_type: str
    applies_when: dict[str, Any]
    llm: str
    mode_default: str
    output_schema: dict[str, Any]
    triple_vocabulary: tuple[str, ...]
    tag_axes: tuple[dict[str, Any], ...]
    destination_path: str
    qa_triggers: tuple[dict[str, Any], ...]
    context_injectors: tuple[dict[str, Any], ...]
    transform_hook: str | None = None


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

    return WorkerAdapterManifest(
        adapter_name=raw["adapter_name"],
        note_type=raw["note_type"],
        applies_when=raw["applies_when"],
        llm=raw["llm"],
        mode_default=raw["mode_default"],
        output_schema=raw["output_schema"],
        triple_vocabulary=tuple(raw["triple_vocabulary"]),
        tag_axes=tuple(raw["tag_axes"]),
        destination_path=raw["destination_path"],
        qa_triggers=tuple(raw.get("qa_triggers", [])),
        context_injectors=tuple(raw.get("context_injectors", [])),
        transform_hook=raw.get("transform_hook"),
    )
