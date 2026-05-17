import pytest
from rufino.engine.ingest.fact_schema import validate_fact, FactSchemaError


SCHEMA = {
    "id": "string",
    "monto": "number",
    "moneda": "enum[ARS, USD]",
}


def test_valid_fact_passes():
    validate_fact({"id": "x", "monto": 100, "moneda": "ARS"}, schema=SCHEMA)


def test_missing_field_raises():
    with pytest.raises(FactSchemaError, match="monto"):
        validate_fact({"id": "x", "moneda": "ARS"}, schema=SCHEMA)


def test_wrong_type_raises():
    with pytest.raises(FactSchemaError, match="number"):
        validate_fact({"id": "x", "monto": "not a number", "moneda": "ARS"}, schema=SCHEMA)


def test_enum_violation_raises():
    with pytest.raises(FactSchemaError, match="enum"):
        validate_fact({"id": "x", "monto": 1, "moneda": "BTC"}, schema=SCHEMA)


def test_unknown_type_spec_raises():
    with pytest.raises(FactSchemaError, match="unknown type spec"):
        validate_fact({"x": "y"}, schema={"x": "numbr"})
