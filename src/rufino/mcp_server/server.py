from rufino.engine.query.api import QueryLayer
from rufino.mcp_server import tools as t


def build_server(ql: QueryLayer):
    """Build an MCP Server registering the 6 ask-rufino tools."""
    from mcp.server import Server
    from mcp.types import Tool, TextContent

    server = Server("ask-rufino")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(name="search_vault", description="Search the vault by query",
                 inputSchema={"type": "object",
                              "properties": {"query": {"type": "string"},
                                             "mode": {"type": "string"},
                                             "k": {"type": "integer"}},
                              "required": ["query"]}),
            Tool(name="find_note", description="Find single best matching note",
                 inputSchema={"type": "object",
                              "properties": {"query": {"type": "string"}},
                              "required": ["query"]}),
            Tool(name="list_triples_for_node", description="Find notes related to a node",
                 inputSchema={"type": "object",
                              "properties": {"node": {"type": "string"},
                                             "relation": {"type": "string"},
                                             "reverse": {"type": "boolean"}},
                              "required": ["node", "relation"]}),
            Tool(name="read_note", description="Read a note by relative path",
                 inputSchema={"type": "object",
                              "properties": {"relative_path": {"type": "string"}},
                              "required": ["relative_path"]}),
            Tool(name="vault_stats", description="Get vault statistics",
                 inputSchema={"type": "object", "properties": {}}),
            Tool(name="list_recent_notes", description="List N most recent notes",
                 inputSchema={"type": "object",
                              "properties": {"k": {"type": "integer"}}}),
        ]

    _ALLOWED_ARGS = {
        "search_vault": {"query", "mode", "k"},
        "find_note": {"query"},
        "list_triples_for_node": {"node", "relation", "reverse"},
        "read_note": {"relative_path"},
        "vault_stats": set(),
        "list_recent_notes": {"k"},
    }
    _HANDLERS = {
        "search_vault": t.search_vault,
        "find_note": t.find_note,
        "list_triples_for_node": t.list_triples_for_node,
        "read_note": t.read_note,
        "vault_stats": t.vault_stats,
        "list_recent_notes": t.list_recent_notes,
    }

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        if name not in _HANDLERS:
            raise ValueError(f"Unknown tool: {name}")
        allowed = _ALLOWED_ARGS[name]
        filtered = {k: v for k, v in (arguments or {}).items() if k in allowed}
        result = _HANDLERS[name](ql, **filtered)

        import json
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    return server
