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
                              "properties": {
                                  "query": {"type": "string"},
                                  "mode": {
                                      "type": "string",
                                      "enum": ["auto", "lexical", "semantic", "hybrid"],
                                      "default": "auto",
                                  },
                                  "k": {
                                      "type": "integer",
                                      "minimum": 1,
                                      "maximum": 100,
                                      "default": 10,
                                  },
                              },
                              "required": ["query"]}),
            Tool(name="find_note", description="Find single best matching note",
                 inputSchema={"type": "object",
                              "properties": {"query": {"type": "string"}},
                              "required": ["query"]}),
            Tool(name="list_triples_for_node",
                 description=(
                     "Traverse triples on a node. reverse=False (default): "
                     "node is a subject note path, returns the objects it "
                     "points to via relation. reverse=True: node is an object, "
                     "returns subject note paths pointing to it."
                 ),
                 inputSchema={"type": "object",
                              "properties": {"node": {"type": "string"},
                                             "relation": {"type": "string"},
                                             "reverse": {"type": "boolean",
                                                         "default": False}},
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

    import logging
    _log = logging.getLogger(__name__)
    vault_path_str = str(ql.vault_root)

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        if name not in _HANDLERS:
            raise ValueError(f"Unknown tool: {name}")
        allowed = _ALLOWED_ARGS[name]
        provided = set((arguments or {}).keys())
        unknown = provided - allowed
        if unknown:
            raise ValueError(f"Unknown arguments for {name!r}: {sorted(unknown)}")
        try:
            result = _HANDLERS[name](ql, **(arguments or {}))
        except Exception as e:
            _log.exception("MCP tool %s raised", name)
            # Redact any absolute vault path leaking through error messages.
            msg = str(e).replace(vault_path_str, "<vault>")
            raise ValueError(msg) from None

        import json
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    return server
