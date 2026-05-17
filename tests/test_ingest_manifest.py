import pytest
from rufino.engine.ingest.manifest import (
    IngestAdapterManifest,
    parse_ingest_manifest,
    ManifestParseError,
)


EMIT_FACT_YAML = """
adapter_name: belo
source_name: belo
schedule: "*/30 * * * *"
auth:
  type: oauth2
  keychain_service: rufino-belo-oauth
output_mode: emit_fact
emits: [transaccion]
fact_schema:
  id: string
  monto: number
  moneda: enum[ARS, USD]
destination:
  facts: belo/facts/<YYYY-MM-DD>-<id>.md
  raw: belo/raw/<id>.json
dedup_by: id
"""

IMPORT_RAW_YAML = """
adapter_name: drive-pdfs
source_name: drive_pdfs
schedule: "0 */6 * * *"
auth:
  type: oauth2
  keychain_service: rufino-drive
output_mode: import_raw
target_inbox: rufino/inbox/
process_with: apunte-clase
trigger: immediate
"""


def test_parses_emit_fact():
    m = parse_ingest_manifest(EMIT_FACT_YAML)
    assert m.output_mode == "emit_fact"
    assert m.dedup_by == "id"
    assert m.fact_schema["monto"] == "number"


def test_parses_import_raw():
    m = parse_ingest_manifest(IMPORT_RAW_YAML)
    assert m.output_mode == "import_raw"
    assert m.target_inbox == "rufino/inbox/"
    assert m.process_with == "apunte-clase"
    assert m.trigger == "immediate"


def test_invalid_output_mode_raises():
    yaml = EMIT_FACT_YAML.replace("output_mode: emit_fact", "output_mode: bogus")
    with pytest.raises(ManifestParseError, match="output_mode"):
        parse_ingest_manifest(yaml)


def test_import_raw_missing_process_with_raises():
    yaml = IMPORT_RAW_YAML.replace("process_with: apunte-clase\n", "")
    with pytest.raises(ManifestParseError, match="process_with"):
        parse_ingest_manifest(yaml)
