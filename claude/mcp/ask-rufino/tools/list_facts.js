// list_facts: lista archivos en `<source>/facts/` del vault.
// Sources conocidos: applehealth, calendar, browsing, screentime, spotify,
// gdrive, youtube, github, elberr, whatsapp.

import fs from "node:fs";
import path from "node:path";
import {
  VAULT_PATH,
  walkMarkdown,
  toRelative,
  extractTitle,
  safeMtime,
  parseDate,
  readFileSafe,
} from "./util.js";

export const definition = {
  name: "list_facts",
  description:
    "Lista facts (`<source>/facts/*.md`) del vault. Filtros opcionales por source y `since` (ISO date — usa mtime).",
  inputSchema: {
    type: "object",
    properties: {
      source: {
        type: "string",
        description:
          "Source a filtrar (calendar, spotify, gdrive, whatsapp, etc.). Si no se pasa, recorre todos.",
      },
      since: {
        type: "string",
        description: "ISO date (YYYY-MM-DD). Solo facts con mtime >= since.",
      },
      limit: {
        type: "number",
        description: "Cantidad máxima (default 50).",
        default: 50,
      },
    },
  },
};

function discoverSources() {
  const out = [];
  let entries;
  try {
    entries = fs.readdirSync(VAULT_PATH, { withFileTypes: true });
  } catch {
    return out;
  }
  for (const ent of entries) {
    if (!ent.isDirectory()) continue;
    const factsDir = path.join(VAULT_PATH, ent.name, "facts");
    try {
      const st = fs.statSync(factsDir);
      if (st.isDirectory()) out.push(ent.name);
    } catch {}
  }
  return out;
}

export async function handler({ source, since, limit = 50 }) {
  const sources = source ? [source] : discoverSources();
  const sinceDate = parseDate(since);
  const sinceMs = sinceDate ? sinceDate.getTime() : 0;

  const items = [];
  for (const src of sources) {
    const factsDir = path.join(VAULT_PATH, src, "facts");
    try {
      if (!fs.statSync(factsDir).isDirectory()) continue;
    } catch {
      continue;
    }
    const files = walkMarkdown(factsDir);
    for (const abs of files) {
      const mtime = safeMtime(abs);
      if (sinceMs && mtime < sinceMs) continue;
      let title = path.basename(abs, ".md");
      try {
        const content = readFileSafe(abs);
        title = extractTitle(abs, content);
      } catch {}
      items.push({
        source: src,
        path: toRelative(abs),
        title,
        mtime,
      });
    }
  }

  items.sort((a, b) => b.mtime - a.mtime);
  const top = items.slice(0, limit).map((i) => ({
    source: i.source,
    path: i.path,
    title: i.title,
    mtime: new Date(i.mtime).toISOString(),
  }));

  return {
    source: source || "(all)",
    since: since || null,
    sources_scanned: sources,
    total: items.length,
    returned: top.length,
    facts: top,
  };
}
