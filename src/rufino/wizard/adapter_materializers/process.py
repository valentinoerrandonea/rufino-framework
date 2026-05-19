from pathlib import Path

import yaml

from rufino.engine.process.manifest import ManifestParseError, parse_worker_manifest
from rufino.runtime.transaction_log import TransactionLog, apply_and_log
from rufino.wizard.spec_schema import ProcessSpec


# The wizard ProcessSpec captures the full processing contract (output_schema,
# triples, tags, qa, context injectors), so "full" is the only sensible default.
# Light/lint modes are user-driven runtime overrides, not adapter defaults.
_DEFAULT_MODE = "full"


def materialize_process(
    *,
    spec: ProcessSpec,
    base_dir: Path,
    vault_slug: str,
    tx_log: TransactionLog,
) -> Path:
    """Materialize a Process adapter dir (manifest.yaml + prompt.md) from a ProcessSpec.

    Raises:
        ValueError: when the assembled manifest does not pass validation.
    """
    adapter_dir = base_dir / "adapters" / "process" / vault_slug / spec.adapter_name
    apply_and_log(
        tx_log,
        op="mkdir",
        target=str(adapter_dir),
        apply_fn=lambda: adapter_dir.mkdir(parents=True),
        rollback="rmdir",
    )

    manifest = _spec_to_manifest_dict(spec)
    manifest_yaml = yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True)
    try:
        parse_worker_manifest(manifest_yaml)
    except ManifestParseError as e:
        raise ValueError(
            f"Process adapter {spec.adapter_name!r} produced invalid manifest: {e}"
        ) from e

    manifest_path = adapter_dir / "manifest.yaml"
    apply_and_log(
        tx_log,
        op="write",
        target=str(manifest_path),
        apply_fn=lambda: manifest_path.write_text(manifest_yaml, encoding="utf-8"),
        rollback="delete",
    )
    prompt_path = adapter_dir / "prompt.md"
    apply_and_log(
        tx_log,
        op="write",
        target=str(prompt_path),
        apply_fn=lambda: prompt_path.write_text(spec.prompt_instructions, encoding="utf-8"),
        rollback="delete",
    )
    return adapter_dir


def _spec_to_manifest_dict(spec: ProcessSpec) -> dict:
    """Serialize a ProcessSpec into the YAML shape ``parse_worker_manifest`` accepts."""
    return {
        "adapter_name": spec.adapter_name,
        "note_type": spec.note_type,
        "applies_when": _to_plain(spec.applies_when),
        "llm": spec.llm,
        "mode_default": _DEFAULT_MODE,
        "output_schema": _to_plain(spec.output_schema),
        "triple_vocabulary": list(spec.triple_vocabulary),
        "tag_axes": [_to_plain(a) for a in spec.tag_axes],
        "destination_path": spec.destination_path,
        "qa_triggers": [_to_plain(q) for q in spec.qa_triggers],
        "context_injectors": [_to_plain(c) for c in spec.context_injectors],
        "batch_size": spec.batch_size,
    }


def _to_plain(value):
    """Recursively unwrap MappingProxyType/tuples produced by spec _freeze_deep."""
    if hasattr(value, "items"):
        return {k: _to_plain(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [_to_plain(v) for v in value]
    return value
