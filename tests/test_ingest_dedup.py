from pathlib import Path
from rufino.engine.ingest.dedup import DedupStore


def test_first_seen_returns_true_then_false(tmp_path: Path):
    store = DedupStore(tmp_path / "dedup.sqlite")
    assert store.is_new(source="belo", fact_id="tx-1") is True
    store.mark_seen(source="belo", fact_id="tx-1")
    assert store.is_new(source="belo", fact_id="tx-1") is False


def test_different_sources_isolated(tmp_path: Path):
    store = DedupStore(tmp_path / "dedup.sqlite")
    store.mark_seen(source="belo", fact_id="tx-1")
    assert store.is_new(source="mp", fact_id="tx-1") is True


def test_persists_across_instances(tmp_path: Path):
    p = tmp_path / "dedup.sqlite"
    DedupStore(p).mark_seen(source="belo", fact_id="x")
    assert DedupStore(p).is_new(source="belo", fact_id="x") is False
