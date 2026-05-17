import re
from dataclasses import dataclass
from pathlib import PurePosixPath
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


_VERTICAL_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_ENTITY_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


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


def _freeze_deep(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({k: _freeze_deep(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_deep(v) for v in value)
    return value


def _freeze_entry(entry: Any, *, field: str, idx: int) -> Mapping[str, Any]:
    if not isinstance(entry, dict):
        raise SpecError(
            f"{field}[{idx}] must be a dict, got {type(entry).__name__}"
        )
    return _freeze_deep(entry)


def _require_list(raw: dict[str, Any], field: str) -> list[Any]:
    value = raw[field]
    if not isinstance(value, list):
        raise SpecError(f"{field!r} must be a list, got {type(value).__name__}")
    return value


def _validate_vocabulary_path(entity: str, path: Any) -> str:
    if not isinstance(path, str):
        raise SpecError(
            f"vocabulary[{entity!r}] must be a string, got {type(path).__name__}"
        )
    posix = PurePosixPath(path)
    if posix.is_absolute():
        raise SpecError(
            f"vocabulary[{entity!r}] must be a relative path, got absolute {path!r}"
        )
    if ".." in posix.parts:
        raise SpecError(
            f"vocabulary[{entity!r}] must not contain '..' segments, got {path!r}"
        )
    return path


def validate_spec(raw: dict[str, Any]) -> WizardSpec:
    for f in _REQUIRED:
        if f not in raw:
            raise SpecError(f"Missing required field: {f}")

    vertical_name = raw["vertical_name"]
    if not isinstance(vertical_name, str) or not _VERTICAL_NAME_RE.match(vertical_name):
        raise SpecError(
            f"vertical_name must match {_VERTICAL_NAME_RE.pattern!r} "
            f"(lowercase + hyphens, starts with letter, <=64 chars), got {vertical_name!r}"
        )

    patterns = _require_list(raw, "patterns")
    unknown = set(patterns) - KNOWN_PATTERNS
    if unknown:
        raise SpecError(f"Unknown pattern(s) in spec: {sorted(unknown)}")

    entities = _require_list(raw, "entities")
    for e in entities:
        if not isinstance(e, str) or not _ENTITY_NAME_RE.match(e):
            raise SpecError(
                f"entities entries must match {_ENTITY_NAME_RE.pattern!r} "
                f"(lowercase + digits + _ + -, starts with letter, <=64 chars), got {e!r}"
            )

    sources = _require_list(raw, "sources")
    processing = _require_list(raw, "processing")
    outputs = _require_list(raw, "outputs")

    vocabulary = raw["vocabulary"]
    if not isinstance(vocabulary, dict):
        raise SpecError(
            f"'vocabulary' must be a dict, got {type(vocabulary).__name__}"
        )
    entities_set = set(entities)
    extra = set(vocabulary.keys()) - entities_set
    if extra:
        raise SpecError(
            f"vocabulary keys not declared as entities: {sorted(extra)}"
        )
    validated_vocab: dict[str, str] = {}
    for entity, path in vocabulary.items():
        if not isinstance(entity, str) or not _ENTITY_NAME_RE.match(entity):
            raise SpecError(
                f"invalid vocabulary key {entity!r}: must match "
                f"{_ENTITY_NAME_RE.pattern!r}"
            )
        validated_vocab[entity] = _validate_vocabulary_path(entity, path)

    return WizardSpec(
        vertical_name=vertical_name,
        patterns=tuple(patterns),
        entities=tuple(entities),
        sources=tuple(_freeze_entry(s, field="sources", idx=i) for i, s in enumerate(sources)),
        processing=tuple(_freeze_entry(p, field="processing", idx=i) for i, p in enumerate(processing)),
        outputs=tuple(_freeze_entry(o, field="outputs", idx=i) for i, o in enumerate(outputs)),
        vocabulary=MappingProxyType(validated_vocab),
    )
