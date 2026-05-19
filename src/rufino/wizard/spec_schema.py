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
_ADAPTER_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_OUTPUT_MODES = frozenset({"import_raw", "emit_facts", "emit_augmented"})


@dataclass(frozen=True)
class IngestSpec:
    """Typed Ingest source. ``output_mode`` selects which mode-specific
    fields are meaningful; cross-shape validation lives in ``_validate_ingest``."""
    adapter_name: str
    source_name: str
    output_mode: str
    auth: Mapping[str, Any]
    schedule: str | None = None
    # import_raw
    target_inbox: str | None = None
    process_with: str | None = None
    trigger: str | None = None
    # emit_facts
    emits: tuple[str, ...] | None = None
    fact_schema: Mapping[str, Any] | None = None
    destination: Mapping[str, Any] | None = None
    dedup_by: str | None = None
    # emit_augmented
    process_inline_with: str | None = None
    # Optional Python body for `fetcher.py` (any output_mode). When None the
    # materializer writes a NotImplementedError scaffold so the adapter is
    # importable but fail-fast on first run.
    fetcher_body: str | None = None


@dataclass(frozen=True)
class ProcessSpec:
    adapter_name: str
    note_type: str
    applies_when: Mapping[str, Any]
    llm: str
    output_schema: Mapping[str, Any]
    triple_vocabulary: tuple[str, ...]
    tag_axes: tuple[Mapping[str, Any], ...]
    destination_path: str
    qa_triggers: tuple[Mapping[str, Any], ...]
    context_injectors: tuple[Mapping[str, Any], ...]
    batch_size: int
    prompt_instructions: str


@dataclass(frozen=True)
class OutputSpec:
    adapter_name: str
    trigger: Mapping[str, Any]
    query: tuple[Mapping[str, Any], ...]
    delivery: tuple[Mapping[str, Any], ...]
    template_body: str


@dataclass(frozen=True)
class WizardSpec:
    vertical_name: str
    patterns: tuple[str, ...]
    entities: tuple[str, ...]
    sources: tuple[IngestSpec, ...]
    processing: tuple[ProcessSpec, ...]
    outputs: tuple[OutputSpec, ...]
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


def _require_list(raw: dict[str, Any], field_name: str) -> list[Any]:
    value = raw[field_name]
    if not isinstance(value, list):
        raise SpecError(
            f"{field_name!r} must be a list, got {type(value).__name__}"
        )
    return value


def _require_str(d: dict, key: str, *, where: str) -> str:
    v = d.get(key)
    if not isinstance(v, str) or not v:
        raise SpecError(
            f"{where}: {key!r} must be a non-empty string, "
            f"got {type(v).__name__}"
        )
    return v


def _require_mapping(d: dict, key: str, *, where: str) -> Mapping[str, Any]:
    v = d.get(key)
    if not isinstance(v, dict):
        raise SpecError(
            f"{where}: {key!r} must be a mapping, got {type(v).__name__}"
        )
    return v


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


def _validate_ingest(entry: Any, *, idx: int) -> IngestSpec:
    where = f"sources[{idx}]"
    if not isinstance(entry, dict):
        raise SpecError(f"{where} must be a dict, got {type(entry).__name__}")

    adapter_name = _require_str(entry, "adapter_name", where=where)
    if not _ADAPTER_NAME_RE.match(adapter_name):
        raise SpecError(
            f"{where}: adapter_name must match "
            f"{_ADAPTER_NAME_RE.pattern!r}, got {adapter_name!r}"
        )
    source_name = _require_str(entry, "source_name", where=where)
    output_mode = _require_str(entry, "output_mode", where=where)
    if output_mode not in _OUTPUT_MODES:
        raise SpecError(
            f"{where}: output_mode must be one of {sorted(_OUTPUT_MODES)}, "
            f"got {output_mode!r}"
        )
    auth = _require_mapping(entry, "auth", where=where)

    schedule = entry.get("schedule")
    if schedule is not None and not isinstance(schedule, str):
        raise SpecError(
            f"{where}: schedule must be a string or null, "
            f"got {type(schedule).__name__}"
        )

    kwargs: dict[str, Any] = dict(
        adapter_name=adapter_name, source_name=source_name,
        output_mode=output_mode, auth=_freeze_deep(auth),
        schedule=schedule,
    )

    if output_mode == "import_raw":
        kwargs["target_inbox"] = _require_str(entry, "target_inbox", where=where)
        kwargs["process_with"] = _require_str(entry, "process_with", where=where)
        kwargs["trigger"] = _require_str(entry, "trigger", where=where)
    elif output_mode == "emit_facts":
        emits = entry.get("emits")
        if not isinstance(emits, list) or not all(isinstance(e, str) for e in emits):
            raise SpecError(
                f"{where}: emits must be a list of strings for emit_facts mode"
            )
        kwargs["emits"] = tuple(emits)
        kwargs["fact_schema"] = _freeze_deep(
            _require_mapping(entry, "fact_schema", where=where)
        )
        destination = _require_mapping(entry, "destination", where=where)
        facts = destination.get("facts")
        if not isinstance(facts, str) or not facts:
            raise SpecError(
                f"{where}: destination.facts must be a non-empty string path"
            )
        raw_dest = destination.get("raw")
        if raw_dest is not None and not isinstance(raw_dest, str):
            raise SpecError(
                f"{where}: destination.raw must be a string path if present"
            )
        kwargs["destination"] = _freeze_deep(destination)
        kwargs["dedup_by"] = _require_str(entry, "dedup_by", where=where)
    elif output_mode == "emit_augmented":
        kwargs["process_inline_with"] = _require_str(
            entry, "process_inline_with", where=where,
        )

    fetcher_body = entry.get("fetcher_body")
    if fetcher_body is not None and not isinstance(fetcher_body, str):
        raise SpecError(
            f"{where}: fetcher_body must be a string if provided, "
            f"got {type(fetcher_body).__name__}"
        )
    kwargs["fetcher_body"] = fetcher_body

    return IngestSpec(**kwargs)


def _validate_process(entry: Any, *, idx: int) -> ProcessSpec:
    where = f"processing[{idx}]"
    if not isinstance(entry, dict):
        raise SpecError(f"{where} must be a dict, got {type(entry).__name__}")

    adapter_name = _require_str(entry, "adapter_name", where=where)
    if not _ADAPTER_NAME_RE.match(adapter_name):
        raise SpecError(
            f"{where}: adapter_name must match "
            f"{_ADAPTER_NAME_RE.pattern!r}, got {adapter_name!r}"
        )
    note_type = _require_str(entry, "note_type", where=where)
    applies_when = _require_mapping(entry, "applies_when", where=where)
    llm = _require_str(entry, "llm", where=where)
    output_schema = _require_mapping(entry, "output_schema", where=where)
    triple_vocabulary = entry.get("triple_vocabulary", [])
    if not isinstance(triple_vocabulary, list) or not all(
        isinstance(t, str) for t in triple_vocabulary
    ):
        raise SpecError(f"{where}: triple_vocabulary must be a list of strings")
    tag_axes = entry.get("tag_axes", [])
    if not isinstance(tag_axes, list) or not all(isinstance(a, dict) for a in tag_axes):
        raise SpecError(f"{where}: tag_axes must be a list of mappings")
    destination_path = _require_str(entry, "destination_path", where=where)
    qa_triggers = entry.get("qa_triggers", [])
    if not isinstance(qa_triggers, list) or not all(isinstance(q, dict) for q in qa_triggers):
        raise SpecError(f"{where}: qa_triggers must be a list of mappings")
    context_injectors = entry.get("context_injectors", [])
    if not isinstance(context_injectors, list) or not all(
        isinstance(c, dict) for c in context_injectors
    ):
        raise SpecError(f"{where}: context_injectors must be a list of mappings")
    batch_size = entry.get("batch_size")
    if not isinstance(batch_size, int) or batch_size <= 0:
        raise SpecError(
            f"{where}: batch_size must be a positive int, got {batch_size!r}"
        )
    if "prompt_instructions" not in entry:
        raise SpecError(
            f"{where}: prompt_instructions is required (wizard must write the "
            f"adapter's worker prompt body, not leave it to the engine)"
        )
    prompt_instructions = entry["prompt_instructions"]
    if not isinstance(prompt_instructions, str) or not prompt_instructions.strip():
        raise SpecError(
            f"{where}: prompt_instructions must be a non-empty string"
        )

    return ProcessSpec(
        adapter_name=adapter_name,
        note_type=note_type,
        applies_when=_freeze_deep(applies_when),
        llm=llm,
        output_schema=_freeze_deep(output_schema),
        triple_vocabulary=tuple(triple_vocabulary),
        tag_axes=tuple(_freeze_deep(a) for a in tag_axes),
        destination_path=destination_path,
        qa_triggers=tuple(_freeze_deep(q) for q in qa_triggers),
        context_injectors=tuple(_freeze_deep(c) for c in context_injectors),
        batch_size=batch_size,
        prompt_instructions=prompt_instructions,
    )


def _validate_output(entry: Any, *, idx: int) -> OutputSpec:
    where = f"outputs[{idx}]"
    if not isinstance(entry, dict):
        raise SpecError(f"{where} must be a dict, got {type(entry).__name__}")

    adapter_name = _require_str(entry, "adapter_name", where=where)
    if not _ADAPTER_NAME_RE.match(adapter_name):
        raise SpecError(
            f"{where}: adapter_name must match "
            f"{_ADAPTER_NAME_RE.pattern!r}, got {adapter_name!r}"
        )
    trigger = _require_mapping(entry, "trigger", where=where)
    query = entry.get("query", [])
    if not isinstance(query, list) or not all(isinstance(q, dict) for q in query):
        raise SpecError(f"{where}: query must be a list of mappings")
    delivery = entry.get("delivery", [])
    if not isinstance(delivery, list) or not all(isinstance(d, dict) for d in delivery):
        raise SpecError(f"{where}: delivery must be a list of mappings")
    if "template_body" not in entry:
        raise SpecError(
            f"{where}: template_body is required (wizard must write the "
            f"output template body, not leave it to the engine)"
        )
    template_body = entry["template_body"]
    if not isinstance(template_body, str) or not template_body.strip():
        raise SpecError(
            f"{where}: template_body must be a non-empty string"
        )

    return OutputSpec(
        adapter_name=adapter_name,
        trigger=_freeze_deep(trigger),
        query=tuple(_freeze_deep(q) for q in query),
        delivery=tuple(_freeze_deep(d) for d in delivery),
        template_body=template_body,
    )


def _cross_ref_process_with(
    sources: tuple[IngestSpec, ...],
    processing: tuple[ProcessSpec, ...],
) -> None:
    process_names = {p.adapter_name for p in processing}
    for i, s in enumerate(sources):
        for field_name in ("process_with", "process_inline_with"):
            ref = getattr(s, field_name)
            if ref is not None and ref not in process_names:
                raise SpecError(
                    f"sources[{i}].{field_name}={ref!r} does not match any "
                    f"processing[].adapter_name (got {sorted(process_names)})"
                )


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

    sources_raw = _require_list(raw, "sources")
    processing_raw = _require_list(raw, "processing")
    outputs_raw = _require_list(raw, "outputs")

    sources = tuple(_validate_ingest(s, idx=i) for i, s in enumerate(sources_raw))
    processing = tuple(_validate_process(p, idx=i) for i, p in enumerate(processing_raw))
    outputs = tuple(_validate_output(o, idx=i) for i, o in enumerate(outputs_raw))

    _cross_ref_process_with(sources, processing)

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
        sources=sources,
        processing=processing,
        outputs=outputs,
        vocabulary=MappingProxyType(validated_vocab),
    )
