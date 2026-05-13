// read_note: lee una nota del vault por path relativo.

import fs from "node:fs";
import { resolveSafe, toRelative } from "./util.js";

export const definition = {
  name: "read_note",
  description:
    "Lee el contenido completo de una nota del vault. `path` es relativo al vault root (ej: `proyectos/umbru/umbruOverview.md`).",
  inputSchema: {
    type: "object",
    properties: {
      path: {
        type: "string",
        description: "Path relativo al vault root.",
      },
    },
    required: ["path"],
  },
};

export async function handler({ path: relPath }) {
  if (!relPath || typeof relPath !== "string") {
    throw new Error("path es requerido");
  }
  const abs = resolveSafe(relPath);
  let stat;
  try {
    stat = fs.statSync(abs);
  } catch {
    throw new Error(`No existe: ${relPath}`);
  }
  if (!stat.isFile()) {
    throw new Error(`No es un archivo: ${relPath}`);
  }
  const content = fs.readFileSync(abs, "utf8");
  return {
    path: toRelative(abs),
    size: content.length,
    mtime: new Date(stat.mtimeMs).toISOString(),
    content,
  };
}
