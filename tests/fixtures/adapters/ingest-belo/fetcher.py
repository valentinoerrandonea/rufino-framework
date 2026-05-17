"""Stub fetcher returning canned transactions for tests."""

CANNED = [
    {"id": "tx-001", "monto": 100.0, "moneda": "ARS", "fecha": "2026-05-16T10:00:00Z"},
    {"id": "tx-002", "monto": 50.0, "moneda": "USD", "fecha": "2026-05-16T11:00:00Z"},
]


def fetch(since: str | None) -> list[dict]:
    """Return all canned facts. `since` is ignored in this stub."""
    return CANNED
