// search_vault: full-text search en el vault con ranking por mtime + match count.

import {
  VAULT_PATH,
  walkMarkdown,
  toRelative,
  extractTitle,
  makeSnippet,
  safeMtime,
  readFileSafe,
} from "./util.js";

export const definition = {
  name: "search_vault",
  description:
    "Full-text search en el vault de Obsidian. Ranking por número de matches y mtime reciente. Devuelve top N con path relativo, título y snippet.",
  inputSchema: {
    type: "object",
    properties: {
      query: {
        type: "string",
        description: "Texto a buscar (case-insensitive).",
      },
      limit: {
        type: "number",
        description: "Cantidad máxima de resultados (default 10).",
        default: 10,
      },
    },
    required: ["query"],
  },
};

export async function handler({ query, limit = 10 }) {
  if (!query || typeof query !== "string" || !query.trim()) {
    throw new Error("query es requerido y debe ser un string no vacío");
  }
  const needle = query.toLowerCase();
  const files = walkMarkdown(VAULT_PATH);
  const results = [];

  for (const abs of files) {
    let content;
    try {
      content = readFileSafe(abs);
    } catch {
      continue;
    }
    const lower = content.toLowerCase();
    let count = 0;
    let idx = 0;
    while ((idx = lower.indexOf(needle, idx)) !== -1) {
      count++;
      idx += needle.length;
      if (count > 100) break; // cap por archivo
    }
    if (count === 0) continue;
    results.push({
      path: toRelative(abs),
      title: extractTitle(abs, content),
      snippet: makeSnippet(content, query),
      matches: count,
      mtime: safeMtime(abs),
    });
  }

  // Ranking: matches DESC, después mtime DESC.
  results.sort((a, b) => b.matches - a.matches || b.mtime - a.mtime);
  const top = results.slice(0, limit).map((r) => ({
    path: r.path,
    title: r.title,
    snippet: r.snippet,
    matches: r.matches,
    mtime: new Date(r.mtime).toISOString(),
  }));

  return {
    query,
    total_matches: results.length,
    returned: top.length,
    results: top,
  };
}
