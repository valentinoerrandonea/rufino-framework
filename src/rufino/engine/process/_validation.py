"""Cross-engine validators shared by spec_schema (wizard) and manifest
(worker adapter parser). Living here keeps the constraint definition in one
place; each call site wraps the raised ``ValueError`` into its own domain
error type with richer context (file path, entry index, etc.)."""
from __future__ import annotations


def validate_compression_floor(value: object) -> float | None:
    if value is None:
        return None
    # bool is an int subclass in Python; the explicit guard prevents
    # ``compression_floor: true`` from silently coercing to 1.0.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(
            f"compression_floor must be a number, got {type(value).__name__}"
        )
    f = float(value)
    if not (0.0 <= f <= 1.0):
        raise ValueError(f"compression_floor must be in [0.0, 1.0], got {value}")
    return f
