from pathlib import Path

import yaml

from rufino.engine.output.manifest import ManifestParseError, parse_output_manifest
from rufino.runtime.transaction_log import TransactionLog, apply_and_log
from rufino.wizard.spec_schema import OutputSpec


# The output manifest stores the template body in a separate file and
# references it by relative path. The wizard captures the body inline as
# `OutputSpec.template_body`, so we write it to `template.md` at materialize
# time and point the manifest at that filename.
_TEMPLATE_FILENAME = "template.md"


def materialize_output(
    *,
    spec: OutputSpec,
    base_dir: Path,
    vault_slug: str,
    tx_log: TransactionLog,
) -> Path:
    """Materialize an Output adapter dir (manifest.yaml + template.md) from an OutputSpec.

    Raises:
        ValueError: when the assembled manifest does not pass validation.
    """
    adapter_dir = base_dir / "adapters" / "output" / vault_slug / spec.adapter_name
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
        parse_output_manifest(manifest_yaml)
    except ManifestParseError as e:
        raise ValueError(
            f"Output adapter {spec.adapter_name!r} produced invalid manifest: {e}"
        ) from e

    manifest_path = adapter_dir / "manifest.yaml"
    apply_and_log(
        tx_log,
        op="write",
        target=str(manifest_path),
        apply_fn=lambda: manifest_path.write_text(manifest_yaml, encoding="utf-8"),
        rollback="delete",
    )
    template_path = adapter_dir / _TEMPLATE_FILENAME
    apply_and_log(
        tx_log,
        op="write",
        target=str(template_path),
        apply_fn=lambda: template_path.write_text(spec.template_body, encoding="utf-8"),
        rollback="delete",
    )
    return adapter_dir


def _spec_to_manifest_dict(spec: OutputSpec) -> dict:
    return {
        "adapter_name": spec.adapter_name,
        "trigger": _to_plain(spec.trigger),
        "query": [_to_plain(q) for q in spec.query],
        "template": _TEMPLATE_FILENAME,
        "delivery": [_to_plain(d) for d in spec.delivery],
    }


def _to_plain(value):
    """Recursively unwrap MappingProxyType/tuples produced by spec _freeze_deep."""
    if hasattr(value, "items"):
        return {k: _to_plain(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [_to_plain(v) for v in value]
    return value
