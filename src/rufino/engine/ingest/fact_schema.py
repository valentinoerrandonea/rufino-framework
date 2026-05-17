import re
from typing import Any


class FactSchemaError(Exception):
    """Raised when a fact does not match its declared schema."""


_ENUM_RE = re.compile(r"^enum\[(.+)\]$")


def validate_fact(fact: dict[str, Any], *, schema: dict[str, str]) -> None:
    for field_name, type_spec in schema.items():
        if field_name not in fact:
            raise FactSchemaError(f"Required field missing: {field_name}")
        value = fact[field_name]
        _check_type(field_name, value, type_spec)


def _check_type(field: str, value: Any, type_spec: str) -> None:
    if type_spec == "string":
        if not isinstance(value, str):
            raise FactSchemaError(f"{field}: expected string, got {type(value).__name__}")
    elif type_spec == "number":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise FactSchemaError(f"{field}: expected number, got {type(value).__name__}")
    elif type_spec == "datetime":
        if not isinstance(value, str):
            raise FactSchemaError(f"{field}: expected datetime string, got {type(value).__name__}")
    elif (m := _ENUM_RE.match(type_spec)):
        options = [s.strip() for s in m.group(1).split(",")]
        if value not in options:
            raise FactSchemaError(f"{field}: expected enum {options}, got {value!r}")
    else:
        raise FactSchemaError(f"{field}: unknown type spec {type_spec!r}")
