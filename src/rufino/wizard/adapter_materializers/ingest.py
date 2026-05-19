from pathlib import Path

import yaml

from rufino.engine.ingest.manifest import ManifestParseError, parse_ingest_manifest
from rufino.runtime.transaction_log import TransactionLog, apply_and_log
from rufino.wizard.spec_schema import IngestSpec


# Spec → engine manifest output_mode translation.
# The wizard spec uses "emit_facts" (plural) but the engine manifest expects
# the singular "emit_fact". Keep both vocabularies; translate at the boundary.
_OUTPUT_MODE_TRANSLATIONS = {"emit_facts": "emit_fact"}


_SCAFFOLD_FETCHER = '''"""TODO: implementar fetch(cursor) para este adapter.

Contrato: ver docs/primitives/ingest.md. Hasta que esto se escriba,
`rufino ingest <adapter_dir>` lanzará NotImplementedError de forma explícita.
"""


def fetch(cursor):
    raise NotImplementedError(
        "fetcher.py no implementado — el wizard generó un scaffold. "
        "Editar este archivo para devolver (records, new_cursor)."
    )
'''


def materialize_ingest(
    *,
    spec: IngestSpec,
    base_dir: Path,
    vault_slug: str,
    tx_log: TransactionLog,
) -> Path:
    """Materialize an Ingest adapter directory from a typed IngestSpec.

    Writes ``<base_dir>/adapters/ingest/<vault_slug>/<adapter_name>/manifest.yaml``,
    validates it against ``parse_ingest_manifest`` before recording, and registers
    every disk op with ``tx_log`` so a caller can roll back on later failure.

    Raises:
        ValueError: when the assembled manifest does not pass validation.
    """
    adapter_dir = base_dir / "adapters" / "ingest" / vault_slug / spec.adapter_name
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
        parse_ingest_manifest(manifest_yaml)
    except ManifestParseError as e:
        raise ValueError(
            f"Ingest adapter {spec.adapter_name!r} produced invalid manifest: {e}"
        ) from e

    manifest_path = adapter_dir / "manifest.yaml"
    apply_and_log(
        tx_log,
        op="write",
        target=str(manifest_path),
        apply_fn=lambda: manifest_path.write_text(manifest_yaml, encoding="utf-8"),
        rollback="delete",
    )

    fetcher_path = adapter_dir / "fetcher.py"
    fetcher_body = spec.fetcher_body or _SCAFFOLD_FETCHER
    apply_and_log(
        tx_log,
        op="write",
        target=str(fetcher_path),
        apply_fn=lambda: fetcher_path.write_text(fetcher_body, encoding="utf-8"),
        rollback="delete",
    )

    if spec.transform_hook_body is not None:
        transform_path = adapter_dir / "transform.py"
        body = spec.transform_hook_body
        apply_and_log(
            tx_log,
            op="write",
            target=str(transform_path),
            apply_fn=lambda: transform_path.write_text(body, encoding="utf-8"),
            rollback="delete",
        )
    return adapter_dir


def _spec_to_manifest_dict(spec: IngestSpec) -> dict:
    """Serialize an IngestSpec into the YAML shape ``parse_ingest_manifest`` accepts."""
    output_mode = _OUTPUT_MODE_TRANSLATIONS.get(spec.output_mode, spec.output_mode)
    # `schedule` is always present in the manifest (even as null), so the
    # engine parser's required-field check doesn't reject on-demand ingests.
    d: dict = {
        "adapter_name": spec.adapter_name,
        "source_name": spec.source_name,
        "output_mode": output_mode,
        "schedule": spec.schedule,
        "auth": _to_plain(spec.auth),
    }

    # Mode-specific fields. Each one is None unless the spec was built for that
    # mode, so we copy only what's present.
    if spec.target_inbox is not None:
        d["target_inbox"] = spec.target_inbox
    if spec.process_with is not None:
        d["process_with"] = spec.process_with
    if spec.trigger is not None:
        d["trigger"] = spec.trigger
    if spec.emits is not None:
        d["emits"] = list(spec.emits)
    if spec.fact_schema is not None:
        d["fact_schema"] = _to_plain(spec.fact_schema)
    if spec.destination is not None:
        d["destination"] = _to_plain(spec.destination)
    if spec.dedup_by is not None:
        d["dedup_by"] = spec.dedup_by
    if spec.process_inline_with is not None:
        d["process_inline_with"] = spec.process_inline_with
    if spec.transform_hook_body is not None:
        d["transform_hook"] = "transform.py"
    return d


def _to_plain(value):
    """Recursively unwrap MappingProxyType/tuples produced by spec _freeze_deep."""
    if hasattr(value, "items"):
        return {k: _to_plain(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [_to_plain(v) for v in value]
    return value
