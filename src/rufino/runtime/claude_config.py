"""Register the ask-rufino MCP server in the user's `~/.claude.json`.

Atomic update: load → mutate → tmp+replace. Preserves other top-level keys
(e.g. `theme`, `permissions`) and other MCP servers.
"""
import json
import os
from pathlib import Path


def register_mcp_server(
    *,
    claude_config_path: Path,
    server_name: str,
    command: str,
    args: list[str],
) -> None:
    """Atomically register/update an MCP server entry in claude_config_path."""
    if claude_config_path.exists():
        try:
            cfg = json.loads(claude_config_path.read_text(encoding="utf-8"))
            if not isinstance(cfg, dict):
                cfg = {}
        except json.JSONDecodeError:
            cfg = {}
    else:
        cfg = {}

    servers = cfg.setdefault("mcpServers", {})
    servers[server_name] = {"command": command, "args": list(args)}

    tmp = claude_config_path.with_suffix(claude_config_path.suffix + ".tmp")
    claude_config_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps(cfg, indent=2))
            f.flush()
            os.fsync(f.fileno())
        tmp.replace(claude_config_path)
    finally:
        if tmp.exists():
            tmp.unlink()
