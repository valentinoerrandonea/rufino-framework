import pytest
from rufino.engine.output.manifest import (
    OutputAdapterManifest,
    parse_output_manifest,
    ManifestParseError,
)


CRON_YAML = """
adapter_name: digest-semanal-facultad
trigger:
  type: cron
  expression: "0 18 * * 5"
query:
  - { name: notas_semana, expression: "created >= 7 days ago" }
template: ./templates/digest.md
delivery:
  - { channel: file, path: "general/digests/<YYYY-WW>.md" }
  - { channel: email, to: "user@example.com", subject: "Digest" }
"""

ON_EVENT_YAML = """
adapter_name: meeting-prep
trigger:
  type: on_event
  event: calendar_event
  filter: "tag = '1:1' AND starts_in_hours < 24"
query:
  - { name: notas, expression: "tag = persona/<event.attendee>" }
template: ./templates/prep.md
delivery:
  - { channel: file, path: "meetings/<event.attendee>/<YYYY-MM-DD>-1on1.md" }
"""


def test_parses_cron_trigger():
    m = parse_output_manifest(CRON_YAML)
    assert m.trigger_type == "cron"
    assert m.cron_expression == "0 18 * * 5"
    assert len(m.delivery) == 2


def test_parses_on_event_trigger():
    m = parse_output_manifest(ON_EVENT_YAML)
    assert m.trigger_type == "on_event"
    assert m.event_name == "calendar_event"
    assert "1:1" in m.event_filter


def test_invalid_trigger_type_raises():
    yaml = CRON_YAML.replace("type: cron", "type: bogus")
    with pytest.raises(ManifestParseError, match="trigger.type"):
        parse_output_manifest(yaml)


def test_missing_template_raises():
    yaml = CRON_YAML.replace("template: ./templates/digest.md\n", "")
    with pytest.raises(ManifestParseError, match="template"):
        parse_output_manifest(yaml)


def test_absolute_template_path_rejected():
    yaml = CRON_YAML.replace("./templates/digest.md", "/etc/passwd")
    with pytest.raises(ManifestParseError, match="template.*relative"):
        parse_output_manifest(yaml)


def test_template_with_parent_escape_rejected():
    yaml = CRON_YAML.replace("./templates/digest.md", "../../etc/passwd")
    with pytest.raises(ManifestParseError, match=r"template.*\.\."):
        parse_output_manifest(yaml)


def test_file_delivery_absolute_path_rejected():
    yaml = CRON_YAML.replace('"general/digests/<YYYY-WW>.md"', '"/etc/passwd"')
    with pytest.raises(ManifestParseError, match=r"delivery\[0\].path.*relative"):
        parse_output_manifest(yaml)


def test_file_delivery_parent_escape_rejected():
    yaml = CRON_YAML.replace('"general/digests/<YYYY-WW>.md"', '"../../etc/passwd"')
    with pytest.raises(ManifestParseError, match=r"delivery\[0\].path.*\.\."):
        parse_output_manifest(yaml)


def test_manifest_query_and_delivery_are_immutable():
    m = parse_output_manifest(CRON_YAML)
    with pytest.raises(TypeError):
        m.delivery[0]["channel"] = "evil"  # type: ignore[index]
