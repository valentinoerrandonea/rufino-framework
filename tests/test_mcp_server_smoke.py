from pathlib import Path
import pytest

from rufino.mcp_server.server import build_server
from rufino.engine.query.api import QueryLayer


class FakeEmbeddings:
    def embed(self, text):
        return [0.0] * 8


def test_server_builds_with_query_layer(tmp_vault: Path):
    ql = QueryLayer(vault_root=tmp_vault, embedder=FakeEmbeddings())
    server = build_server(ql)
    assert server is not None


def test_call_tool_rejects_unknown_arguments(tmp_vault: Path):
    """A client sending an unknown kwarg must get a clear error, not silent drop."""
    import asyncio
    ql = QueryLayer(vault_root=tmp_vault, embedder=FakeEmbeddings())
    server = build_server(ql)
    handler = server.request_handlers[__import__("mcp.types", fromlist=["CallToolRequest"]).CallToolRequest]

    from mcp.types import CallToolRequest, CallToolRequestParams
    req = CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(name="find_note", arguments={"query": "x", "bogus": 1}),
    )
    result = asyncio.run(handler(req))
    assert result.root.isError is True
    assert "bogus" in result.root.content[0].text.lower() or "unknown" in result.root.content[0].text.lower()
