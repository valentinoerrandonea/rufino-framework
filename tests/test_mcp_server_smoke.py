from pathlib import Path

from rufino.mcp_server.server import build_server
from rufino.engine.query.api import QueryLayer


class FakeEmbeddings:
    def embed(self, text):
        return [0.0] * 8


def test_server_builds_with_query_layer(tmp_vault: Path):
    ql = QueryLayer(vault_root=tmp_vault, embedder=FakeEmbeddings())
    server = build_server(ql)
    assert server is not None
