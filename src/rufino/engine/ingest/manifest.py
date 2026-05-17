from dataclasses import dataclass
from typing import Any
import yaml


class ManifestParseError(Exception):
    """Raised when ingest adapter manifest is invalid."""


VALID_OUTPUT_MODES = {"emit_fact", "import_raw", "emit_augmented"}
VALID_TRIGGERS = {"immediate", "defer"}


@dataclass(frozen=True)
class IngestAdapterManifest:
    adapter_name: str
    source_name: str
    schedule: str
    auth: dict[str, Any]
    output_mode: str
    emits: tuple[str, ...] = ()
    fact_schema: dict[str, Any] = None  # type: ignore
    destination_facts: str | None = None
    destination_raw: str | None = None
    dedup_by: str | None = None
    target_inbox: str | None = None
    process_with: str | None = None
    trigger: str = "immediate"
    process_inline_with: str | None = None
    transform_hook: str | None = None


_REQUIRED_SHARED = ("adapter_name", "source_name", "schedule", "output_mode")


def parse_ingest_manifest(yaml_text: str) -> IngestAdapterManifest:
    try:
        raw = yaml.safe_load(yaml_text)
    except yaml.YAMLError as e:
        raise ManifestParseError(f"Invalid YAML: {e}") from e

    if not isinstance(raw, dict):
        raise ManifestParseError("Manifest root must be a mapping")

    missing = [f for f in _REQUIRED_SHARED if f not in raw]
    if missing:
        raise ManifestParseError(f"Missing required fields: {missing}")

    mode = raw["output_mode"]
    if mode not in VALID_OUTPUT_MODES:
        raise ManifestParseError(
            f"output_mode must be one of {VALID_OUTPUT_MODES}, got {mode!r}"
        )

    common = dict(
        adapter_name=raw["adapter_name"],
        source_name=raw["source_name"],
        schedule=raw["schedule"],
        auth=raw.get("auth", {}),
        output_mode=mode,
        transform_hook=raw.get("transform_hook"),
    )

    if mode == "emit_fact":
        for f in ("emits", "fact_schema", "destination", "dedup_by"):
            if f not in raw:
                raise ManifestParseError(f"emit_fact requires field {f!r}")
        dest = raw["destination"]
        return IngestAdapterManifest(
            **common,
            emits=tuple(raw["emits"]),
            fact_schema=raw["fact_schema"],
            destination_facts=dest.get("facts"),
            destination_raw=dest.get("raw"),
            dedup_by=raw["dedup_by"],
        )

    if mode == "import_raw":
        for f in ("target_inbox", "process_with"):
            if f not in raw:
                raise ManifestParseError(f"import_raw requires field {f!r}")
        trigger = raw.get("trigger", "immediate")
        if trigger not in VALID_TRIGGERS:
            raise ManifestParseError(f"trigger must be one of {VALID_TRIGGERS}")
        return IngestAdapterManifest(
            **common,
            target_inbox=raw["target_inbox"],
            process_with=raw["process_with"],
            trigger=trigger,
        )

    if "process_inline_with" not in raw:
        raise ManifestParseError("emit_augmented requires process_inline_with")
    return IngestAdapterManifest(
        **common,
        process_inline_with=raw["process_inline_with"],
    )
