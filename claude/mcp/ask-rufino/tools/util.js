// Utilidades compartidas para tools del MCP ask-rufino.
// Acceso read-only al vault.

import fs from "node:fs";
import path from "node:path";

export const VAULT_PATH =
  process.env.RUFINO_VAULT_PATH || "/Users/val/Files/vaultlentino";

// Directorios que ignoramos siempre (artefactos, no notas).
const IGNORED_DIRS = new Set([
  ".git",
  ".obsidian",
  "_trash",
  "node_modules",
  ".DS_Store",
]);

/**
 * Recorre el vault recursivamente y devuelve paths absolutos de archivos .md.
 * @param {string} root
 * @param {(absPath: string) => boolean} [filter]
 * @returns {string[]}
 */
export function walkMarkdown(root, filter) {
  const out = [];
  const stack = [root];
  while (stack.length) {
    const dir = stack.pop();
    let entries;
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch {
      continue;
    }
    for (const ent of entries) {
      if (IGNORED_DIRS.has(ent.name)) continue;
      const abs = path.join(dir, ent.name);
      if (ent.isDirectory()) {
        stack.push(abs);
      } else if (ent.isFile() && ent.name.endsWith(".md")) {
        if (!filter || filter(abs)) out.push(abs);
      }
    }
  }
  return out;
}

/**
 * Path relativo al vault root, normalizado con forward slashes.
 */
export function toRelative(absPath) {
  return path.relative(VAULT_PATH, absPath).split(path.sep).join("/");
}

/**
 * Resuelve un path relativo al vault y verifica que esté contenido (anti path traversal).
 */
export function resolveSafe(relPath) {
  const abs = path.resolve(VAULT_PATH, relPath);
  const vaultAbs = path.resolve(VAULT_PATH);
  if (!abs.startsWith(vaultAbs + path.sep) && abs !== vaultAbs) {
    throw new Error(`Path fuera del vault: ${relPath}`);
  }
  return abs;
}

/**
 * Lee primeras N líneas para extraer título (primer H1 o filename).
 */
export function extractTitle(absPath, content) {
  const m = content.match(/^#\s+(.+?)$/m);
  if (m) return m[1].trim();
  return path.basename(absPath, ".md");
}

/**
 * Snippet alrededor de un match (case-insensitive).
 */
export function makeSnippet(content, query, radius = 80) {
  const lower = content.toLowerCase();
  const idx = lower.indexOf(query.toLowerCase());
  if (idx === -1) return content.slice(0, radius * 2).replace(/\s+/g, " ").trim();
  const start = Math.max(0, idx - radius);
  const end = Math.min(content.length, idx + query.length + radius);
  const prefix = start > 0 ? "…" : "";
  const suffix = end < content.length ? "…" : "";
  return (prefix + content.slice(start, end) + suffix).replace(/\s+/g, " ").trim();
}

/**
 * Parsea fecha en formato YYYY-MM-DD o ISO. Devuelve Date o null.
 */
export function parseDate(s) {
  if (!s) return null;
  const d = new Date(s);
  if (isNaN(d.getTime())) return null;
  return d;
}

/**
 * Lee mtime de archivo de forma segura.
 */
export function safeMtime(absPath) {
  try {
    return fs.statSync(absPath).mtimeMs;
  } catch {
    return 0;
  }
}

/**
 * Lee contenido completo. Falla si el archivo no existe.
 */
export function readFileSafe(absPath) {
  return fs.readFileSync(absPath, "utf8");
}
