from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping


class SpecError(Exception):
    """Raised when the wizard spec is invalid."""


KNOWN_PATTERNS = frozenset({
    "discrete_events_with_metadata",
    "long_documents_extraction",
    "person_centric_tracking",
    "decision_log_with_rationale",
    "temporal_self_observation",
    "knowledge_graph_projects",
})


@dataclass(frozen=True)
class WizardSpec:
    vertical_name: str
    patterns: tuple[str, ...]
    entities: tuple[str, ...]
    sources: tuple[Mapping[str, Any], ...]
    processing: tuple[Mapping[str, Any], ...]
    outputs: tuple[Mapping[str, Any], ...]
    vocabulary: Mapping[str, str]


_REQUIRED = (
    "vertical_name", "patterns", "entities", "sources",
    "processing", "outputs", "vocabulary",
)


def _freeze_entry(entry: Any) -> Mapping[str, Any]:
    if not isinstance(entry, dict):
        raise SpecError(f"Entry must be a dict, got {type(entry).__name__}")
    return MappingProxyType(dict(entry))


def validate_spec(raw: dict[str, Any]) -> WizardSpec:
    for f in _REQUIRED:
        if f not in raw:
            raise SpecError(f"Missing required field: {f}")

    if not isinstance(raw["patterns"], list):
        raise SpecError("'patterns' must be a list")
    unknown = set(raw["patterns"]) - KNOWN_PATTERNS
    if unknown:
        raise SpecError(f"Unknown pattern(s) in spec: {sorted(unknown)}")

    if not isinstance(raw["vocabulary"], dict):
        raise SpecError("'vocabulary' must be a dict")

    return WizardSpec(
        vertical_name=str(raw["vertical_name"]),
        patterns=tuple(raw["patterns"]),
        entities=tuple(raw["entities"]),
        sources=tuple(_freeze_entry(s) for s in raw["sources"]),
        processing=tuple(_freeze_entry(p) for p in raw["processing"]),
        outputs=tuple(_freeze_entry(o) for o in raw["outputs"]),
        vocabulary=MappingProxyType(dict(raw["vocabulary"])),
    )
