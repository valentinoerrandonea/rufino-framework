from pathlib import Path
from rufino.engine.ingest.fetcher_loader import load_fetcher


FIXTURE = Path(__file__).parent / "fixtures" / "adapters" / "ingest-belo"


def test_load_fetcher_returns_callable():
    fetcher = load_fetcher(FIXTURE)
    assert callable(fetcher)


def test_loaded_fetcher_returns_facts():
    fetcher = load_fetcher(FIXTURE)
    facts = fetcher(since=None)
    assert len(facts) == 2
    assert facts[0]["id"] == "tx-001"
