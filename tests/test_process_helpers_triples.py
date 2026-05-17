import pytest
from rufino.engine.process.helpers.triples import (
    extract_triples,
    validate_triples_against_vocab,
    TripleError,
)


def test_extract_triples_from_frontmatter():
    fm = {
        "triples": [
            {"r": "tema-de", "o": "ml-i"},
            {"r": "expuesto-por", "o": "mendez"},
        ]
    }
    triples = extract_triples(fm)
    assert triples == [("tema-de", "ml-i"), ("expuesto-por", "mendez")]


def test_no_triples_returns_empty():
    assert extract_triples({}) == []


def test_validate_triples_passes_for_known_relations():
    vocab = {"tema-de", "expuesto-por", "extiende"}
    validate_triples_against_vocab(
        [("tema-de", "x"), ("extiende", "y")],
        vocab,
    )


def test_validate_triples_rejects_unknown_relation():
    vocab = {"tema-de"}
    with pytest.raises(TripleError, match="invented"):
        validate_triples_against_vocab([("invented", "x")], vocab)
