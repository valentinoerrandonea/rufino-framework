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
                 inputSchema={"type": "object", "properties": {"query": {"type": "string"}}}),
            Tool(name="find_note", description="Find single best matching note",
                 inputSchema={"type": "object", "properties": {"query": {"type": "string"}}}),
            Tool(name="list_triples_for_node", description="Find notes related to a node",
                 inputSchema={"type": "object", "properties": {
                     "node": {"type": "string"}, "relation": {"type": "string"}}}),
            Tool(name="read_note", description="Read a note by relative path",
                 inputSchema={"type": "object", "properties": {"relative_path": {"type": "string"}}}),
            Tool(name="vault_stats", description="Get vault statistics",
                 inputSchema={"type": "object", "properties": {}}),
            Tool(name="list_recent_notes", description="List N most recent notes",
                 inputSchema={"type": "object", "properties": {"k": {"type": "integer"}}}),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        if name == "search_vault":
            result = t.search_vault(ql, **arguments)
        elif name == "find_note":
            result = t.find_note(ql, **arguments)
        elif name == "list_triples_for_node":
            result = t.list_triples_for_node(ql, **arguments)
        elif name == "read_note":
            result = t.read_note(ql, **arguments)
        elif name == "vault_stats":
            result = t.vault_stats(ql)
        elif name == "list_recent_notes":
            result = t.list_recent_notes(ql, **arguments)
        else:
            raise ValueError(f"Unknown tool: {name}")

        import json
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    return server
