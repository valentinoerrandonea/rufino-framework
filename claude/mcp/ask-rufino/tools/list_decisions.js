// list_decisions: lista archivos de decisiones en el vault.
// Path real: proyectos/<x>/decisiones/decision*.md (no rufino-core).
// También captura cualquier decision*.md en el vault.

import path from "node:path";
import {
  VAULT_PATH,
  walkMarkdown,
  toRelative,
  extractTitle,
  safeMtime,
  readFileSafe,
} from "./util.js";

export const definition = {
  name: "list_decisions",
  description:
    "Lista archivos `decision*.md` del vault. Si se pasa `project`, filtra a `proyectos/<project>/`. Devuelve ordenado por mtime desc.",
  inputSchema: {
    type: "object",
    properties: {
      project: {
        type: "string",
        description:
          "Slug del proyecto (ej: umbru, notegraph). Si no se pasa, lista decisiones de todo el vault.",
      },
      limit: {
        type: "number",
        description: "Cantidad máxima (default 20).",
        default: 20,
      },
    },
  },
};

export async function handler({ project, limit = 20 }) {
  let root = VAULT_PATH;
  if (project) {
    root = path.join(VAULT_PATH, "proyectos", project);
  }
  const files = walkMarkdown(root, (abs) =>
    path.basename(abs).toLowerCase().startsWith("decision"),
  );

  const items = files.map((abs) => {
    let title = path.basename(abs, ".md");
    try {
      const content = readFileSafe(abs);
      title = extractTitle(abs, content);
    } catch {}
    return {
      path: toRelative(abs),
      title,
      mtime: safeMtime(abs),
    };
  });

  items.sort((a, b) => b.mtime - a.mtime);
  const top = items.slice(0, limit).map((i) => ({
    path: i.path,
    title: i.title,
    mtime: new Date(i.mtime).toISOString(),
  }));

  return {
    project: project || "(all)",
    total: items.length,
    returned: top.length,
    decisions: top,
  };
}
