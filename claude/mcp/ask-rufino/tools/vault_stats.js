// vault_stats: totales del vault (notas por proyecto, facts por source, personas).

import fs from "node:fs";
import path from "node:path";
import { VAULT_PATH, walkMarkdown } from "./util.js";

export const definition = {
  name: "vault_stats",
  description:
    "Totales del vault: cantidad de notas totales, por proyecto, por source de facts, personas, decisiones, sesiones.",
  inputSchema: {
    type: "object",
    properties: {},
  },
};

function safeList(dir) {
  try {
    return fs
      .readdirSync(dir, { withFileTypes: true })
      .filter((d) => d.isDirectory())
      .map((d) => d.name);
  } catch {
    return [];
  }
}

export async function handler() {
  const allFiles = walkMarkdown(VAULT_PATH);

  // Por proyecto.
  const proyectosRoot = path.join(VAULT_PATH, "proyectos");
  const projects = safeList(proyectosRoot);
  const byProject = {};
  for (const p of projects) {
    byProject[p] = walkMarkdown(path.join(proyectosRoot, p)).length;
  }

  // Por source (facts).
  const sources = safeList(VAULT_PATH).filter((s) => {
    try {
      return fs.statSync(path.join(VAULT_PATH, s, "facts")).isDirectory();
    } catch {
      return false;
    }
  });
  const factsBySource = {};
  for (const s of sources) {
    factsBySource[s] = walkMarkdown(path.join(VAULT_PATH, s, "facts")).length;
  }

  // Personas.
  const peopleDir = path.join(VAULT_PATH, "rufino/_people");
  const peopleCount = walkMarkdown(peopleDir).length;

  // Decisiones.
  const decisionsCount = allFiles.filter((f) =>
    path.basename(f).toLowerCase().startsWith("decision"),
  ).length;

  // Sesiones.
  const sesionesDir = path.join(VAULT_PATH, "sesiones");
  const sesionesCount = walkMarkdown(sesionesDir).length;

  return {
    vault_path: VAULT_PATH,
    total_notes: allFiles.length,
    projects: byProject,
    facts_by_source: factsBySource,
    people: peopleCount,
    decisions: decisionsCount,
    sessions: sesionesCount,
  };
}
