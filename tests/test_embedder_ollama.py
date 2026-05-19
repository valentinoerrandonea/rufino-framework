from unittest.mock import MagicMock, patch

import httpx
import pytest

from rufino.runtime.embedder.ollama import OllamaEmbedder


def test_embed_happy_path() -> None:
    with patch("rufino.runtime.embedder.ollama.httpx.post") as mpost:
        mpost.return_value = MagicMock(
            status_code=200,
            json=lambda: {"embedding": [0.1, 0.2, 0.3]},
        )
        mpost.return_value.raise_for_status = MagicMock()
        emb = OllamaEmbedder()
        vec = emb.embed("hola mundo")
    assert vec == [0.1, 0.2, 0.3]
    args, kwargs = mpost.call_args
    assert args[0].endswith("/api/embeddings")
    assert kwargs["json"]["model"] == "nomic-embed-text"
    assert kwargs["json"]["prompt"] == "hola mundo"


def test_embed_timeout_propagates() -> None:
    with patch("rufino.runtime.embedder.ollama.httpx.post",
               side_effect=httpx.ReadTimeout("slow")):
        emb = OllamaEmbedder(timeout=0.01)
        with pytest.raises(httpx.ReadTimeout):
            emb.embed("x")


def test_embed_http_500_propagates() -> None:
    with patch("rufino.runtime.embedder.ollama.httpx.post") as mpost:
        resp = MagicMock(status_code=500)
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500", request=MagicMock(), response=resp,
        )
        mpost.return_value = resp
        with pytest.raises(httpx.HTTPStatusError):
            OllamaEmbedder().embed("x")


def test_custom_model_and_base_url() -> None:
    with patch("rufino.runtime.embedder.ollama.httpx.post") as mpost:
        mpost.return_value = MagicMock(
            status_code=200, json=lambda: {"embedding": [1.0]},
        )
        mpost.return_value.raise_for_status = MagicMock()
        emb = OllamaEmbedder(model="custom-model", base_url="http://x:1234")
        emb.embed("t")
    args, kwargs = mpost.call_args
    assert args[0] == "http://x:1234/api/embeddings"
    assert kwargs["json"]["model"] == "custom-model"
