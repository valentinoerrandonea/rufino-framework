from typing import Any


class TripleError(Exception):
    """Raised when triples are malformed or violate vocabulary."""


def extract_triples(frontmatter: dict[str, Any]) -> list[tuple[str, str]]:
    """Extract (relation, object) pairs from the `triples:` block of frontmatter.

    Frontmatter format: triples: [{r: <relation>, o: <object>}, ...]
    """
    raw = frontmatter.get("triples", [])
    if not isinstance(raw, list):
        raise TripleError("triples must be a list")

    out: list[tuple[str, str]] = []
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict) or "r" not in entry or "o" not in entry:
            raise TripleError(f"triples[{i}] missing 'r' or 'o': {entry!r}")
        out.append((entry["r"], entry["o"]))
    return out


def validate_triples_against_vocab(
    triples: list[tuple[str, str]],
    vocab: set[str],
) -> None:
    """Ensure every relation in `triples` is declared in `vocab`."""
    for r, _ in triples:
        if r not in vocab:
            raise TripleError(f"Unknown/invented relation {r!r}; vocab={sorted(vocab)}")
