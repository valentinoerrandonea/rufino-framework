from unittest.mock import MagicMock, patch

from rufino.runtime.embedder.cross_encoder import CrossEncoderReranker


def test_rerank_orders_by_score_descending() -> None:
    rer = CrossEncoderReranker()
    fake_model = MagicMock()
    fake_model.predict.return_value = [0.1, 0.9, 0.5]
    with patch.object(rer, "_load_model", return_value=fake_model):
        ordered = rer.rerank("q", ["a", "b", "c"])
    assert ordered == ["b", "c", "a"]
    fake_model.predict.assert_called_once_with([("q", "a"), ("q", "b"), ("q", "c")])


def test_rerank_empty_candidates_returns_empty() -> None:
    rer = CrossEncoderReranker()
    fake_model = MagicMock()
    with patch.object(rer, "_load_model", return_value=fake_model):
        assert rer.rerank("q", []) == []
    fake_model.predict.assert_not_called()


def test_rerank_single_candidate_passes_through() -> None:
    rer = CrossEncoderReranker()
    fake_model = MagicMock()
    fake_model.predict.return_value = [0.42]
    with patch.object(rer, "_load_model", return_value=fake_model):
        assert rer.rerank("q", ["only"]) == ["only"]


def test_load_model_caches(monkeypatch) -> None:
    import sys
    import types

    fake_module = types.ModuleType("sentence_transformers")
    mce = MagicMock(return_value="fake-model")
    fake_module.CrossEncoder = mce
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)

    rer = CrossEncoderReranker()
    m1 = rer._load_model()
    m2 = rer._load_model()
    assert m1 is m2 == "fake-model"
    assert mce.call_count == 1
