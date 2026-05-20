import inspect
from unittest.mock import MagicMock, patch

import pytest

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


def test_cross_encoder_pins_revision() -> None:
    """Regression: I-G — el modelo cross-encoder debe estar pinned por revisión.

    Sin un pin, el primer query híbrido descarga la HEAD del modelo (~400 MB).
    """
    import rufino.runtime.embedder.cross_encoder as ce
    src = inspect.getsource(ce)
    assert "revision=" in src, (
        "CrossEncoder debe pasar revision='<sha>' por reproducibilidad"
    )


def test_load_model_uses_pinned_revision(monkeypatch) -> None:
    """Cross-encoder pasa la revision al constructor de sentence_transformers."""
    import sys
    import types

    fake_module = types.ModuleType("sentence_transformers")
    captured: dict = {}

    def fake_ctor(name, **kwargs):
        captured["name"] = name
        captured["kwargs"] = kwargs
        return "fake-model"

    fake_module.CrossEncoder = fake_ctor
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)

    rer = CrossEncoderReranker()
    rer._load_model()
    assert "revision" in captured["kwargs"]
    assert captured["kwargs"]["revision"]  # non-empty


def test_load_model_env_override(monkeypatch) -> None:
    """RUFINO_RERANKER_MODEL y RUFINO_RERANKER_REVISION sobreescriben defaults."""
    import sys
    import types

    fake_module = types.ModuleType("sentence_transformers")
    captured: dict = {}

    def fake_ctor(name, **kwargs):
        captured["name"] = name
        captured["kwargs"] = kwargs
        return "fake-model"

    fake_module.CrossEncoder = fake_ctor
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)
    monkeypatch.setenv("RUFINO_RERANKER_MODEL", "custom/model")
    monkeypatch.setenv("RUFINO_RERANKER_REVISION", "deadbeef")

    rer = CrossEncoderReranker()
    rer._load_model()
    assert captured["name"] == "custom/model"
    assert captured["kwargs"]["revision"] == "deadbeef"
