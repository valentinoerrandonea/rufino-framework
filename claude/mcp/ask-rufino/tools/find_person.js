// find_person: busca personas en `rufino/_people/`.

import path from "node:path";
import {
  VAULT_PATH,
  walkMarkdown,
  toRelative,
  readFileSafe,
} from "./util.js";

const PEOPLE_DIR = "rufino/_people";

export const definition = {
  name: "find_person",
  description:
    "Busca una persona en `rufino/_people/` por nombre, slug o alias. Si hay un único match devuelve el body completo. Si hay varios, lista candidatos.",
  inputSchema: {
    type: "object",
    properties: {
      name: {
        type: "string",
        description:
          "Nombre, slug o substring del archivo / contenido de la persona.",
      },
    },
    required: ["name"],
  },
};

export async function handler({ name }) {
  if (!name || typeof name !== "string" || !name.trim()) {
    throw new Error("name es requerido");
  }
  const needle = name.toLowerCase().trim();
  const peopleRoot = path.join(VAULT_PATH, PEOPLE_DIR);
  const files = walkMarkdown(peopleRoot);

  const matches = [];
  for (const abs of files) {
    const base = path.basename(abs, ".md").toLowerCase();
    const rel = toRelative(abs);
    let content;
    try {
      content = readFileSafe(abs);
    } catch {
      continue;
    }
    // Match si: filename incluye el needle, o frontmatter contiene el alias/persona, o título H1 lo incluye.
    const lower = content.toLowerCase();
    const fileMatch = base.includes(needle);
    // Match más fuerte si arranca con el needle o es exacto.
    let score = 0;
    if (base === needle) score = 100;
    else if (base.startsWith(needle)) score = 60;
    else if (fileMatch) score = 40;
    else if (lower.includes(needle)) score = 10;
    if (score === 0) continue;
    matches.push({ path: rel, score, content, name: base });
  }

  matches.sort((a, b) => b.score - a.score);

  if (matches.length === 0) {
    return { name, found: 0, message: `No se encontró persona para "${name}".` };
  }

  if (matches.length === 1 || matches[0].score >= 60) {
    const m = matches[0];
    return {
      name,
      found: matches.length,
      best_match: {
        path: m.path,
        name: m.name,
        content: m.content,
      },
      others: matches.slice(1, 5).map((x) => ({ path: x.path, name: x.name })),
    };
  }

  return {
    name,
    found: matches.length,
    candidates: matches.slice(0, 10).map((m) => ({
      path: m.path,
      name: m.name,
      score: m.score,
    })),
  };
}
