import pytest
from rufino.engine.memory_loop.validator import VerticalConfigValidator
from rufino.runtime.validator_base import Validator


def test_validator_implements_protocol():
    v = VerticalConfigValidator()
    assert isinstance(v, Validator)


def test_valid_manifest_yields_no_errors():
    v = VerticalConfigValidator()
    manifest = {
        "adapter_name": "ok",
        "vertical_name": "facultad",
        "entity_types": ["a", "b"],
        "note_destinations": {"a": "x/<slug>.md", "b": "y/<slug>.md"},
        "rule_extensions": ["./r.md"],
    }
    result = v.validate(manifest)
    assert result.ok
    assert result.errors == []


def test_destination_referencing_undeclared_entity_warns():
    v = VerticalConfigValidator()
    manifest = {
        "adapter_name": "ok",
        "vertical_name": "x",
        "entity_types": ["a"],
        "note_destinations": {"a": "p/<slug>.md", "ghost": "q/<slug>.md"},
        "rule_extensions": [],
    }
    result = v.validate(manifest)
    assert result.ok  # warnings don't block
    assert any("ghost" in w.message for w in result.warnings)


def test_entity_without_destination_warns():
    v = VerticalConfigValidator()
    manifest = {
        "adapter_name": "ok",
        "vertical_name": "x",
        "entity_types": ["a", "b"],
        "note_destinations": {"a": "p/<slug>.md"},
        "rule_extensions": [],
    }
    result = v.validate(manifest)
    assert result.ok
    assert any("b" in w.message for w in result.warnings)


def test_adapter_name_must_be_kebab_case():
    v = VerticalConfigValidator()
    manifest = {
        "adapter_name": "Bad Name",
        "vertical_name": "x",
        "entity_types": ["a"],
        "note_destinations": {"a": "p/<slug>.md"},
        "rule_extensions": [],
    }
    result = v.validate(manifest)
    assert not result.ok
