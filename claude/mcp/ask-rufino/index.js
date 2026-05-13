#!/usr/bin/env node
// ask-rufino MCP server.
// Stdio transport. Read-only sobre el vault de Obsidian.
// Vault path configurado via RUFINO_VAULT_PATH (default /Users/val/Files/vaultlentino).

import * as searchVault from "./tools/search_vault.js";
import * as findPerson from "./tools/find_person.js";
import * as listDecisions from "./tools/list_decisions.js";
import * as listFacts from "./tools/list_facts.js";
import * as readNote from "./tools/read_note.js";
import * as vaultStats from "./tools/vault_stats.js";
import { VAULT_PATH } from "./tools/util.js";

const TOOLS = [searchVault, findPerson, listDecisions, listFacts, readNote, vaultStats];
const TOOLS_BY_NAME = Object.fromEntries(TOOLS.map((t) => [t.definition.name, t]));

// --- Test mode -------------------------------------------------------------
async function runTestMode() {
  process.stderr.write(`[ask-rufino] test mode — vault: ${VAULT_PATH}\n`);
  const out = {};

  out["search_vault('umbru', limit=10)"] = await searchVault.handler({
    query: "umbru",
    limit: 10,
  });
  out["vault_stats()"] = await vaultStats.handler();
  out["list_decisions('umbru', limit=5)"] = await listDecisions.handler({
    project: "umbru",
    limit: 5,
  });
  out["find_person('alejandro')"] = await findPerson.handler({ name: "alejandro" });
  out["list_facts(source='spotify', limit=3)"] = await listFacts.handler({
    source: "spotify",
    limit: 3,
  });

  process.stdout.write(JSON.stringify(out, null, 2) + "\n");
}

// --- MCP server mode -------------------------------------------------------
async function runMcpServer() {
  // Import dinámico del SDK para que --test funcione aunque el SDK no esté instalado.
  let Server, StdioServerTransport, schemas;
  try {
    ({ Server } = await import("@modelcontextprotocol/sdk/server/index.js"));
    ({ StdioServerTransport } = await import(
      "@modelcontextprotocol/sdk/server/stdio.js"
    ));
    schemas = await import("@modelcontextprotocol/sdk/types.js");
  } catch (err) {
    process.stderr.write(
      `[ask-rufino] ERROR: no se pudo cargar @modelcontextprotocol/sdk.\n` +
        `Corré: cd ~/.claude/mcp/ask-rufino && npm install\n` +
        `Detalle: ${err.message}\n`,
    );
    process.exit(1);
  }

  const { CallToolRequestSchema, ListToolsRequestSchema } = schemas;

  const server = new Server(
    { name: "ask-rufino", version: "0.1.0" },
    { capabilities: { tools: {} } },
  );

  server.setRequestHandler(ListToolsRequestSchema, async () => ({
    tools: TOOLS.map((t) => t.definition),
  }));

  server.setRequestHandler(CallToolRequestSchema, async (request) => {
    const { name, arguments: args } = request.params;
    const tool = TOOLS_BY_NAME[name];
    if (!tool) {
      return {
        content: [{ type: "text", text: `Tool desconocida: ${name}` }],
        isError: true,
      };
    }
    try {
      const result = await tool.handler(args || {});
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    } catch (err) {
      return {
        content: [{ type: "text", text: `Error en ${name}: ${err.message}` }],
        isError: true,
      };
    }
  });

  const transport = new StdioServerTransport();
  await server.connect(transport);
  process.stderr.write(
    `[ask-rufino] MCP server activo (stdio). Vault: ${VAULT_PATH}\n`,
  );
}

// --- Entry -----------------------------------------------------------------
const isTest = process.argv.includes("--test");

(async () => {
  try {
    if (isTest) {
      await runTestMode();
      process.exit(0);
    } else {
      await runMcpServer();
    }
  } catch (err) {
    process.stderr.write(`[ask-rufino] fatal: ${err.stack || err.message}\n`);
    process.exit(1);
  }
})();
