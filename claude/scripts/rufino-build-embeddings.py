#!/usr/bin/env python3
"""
rufino-build-embeddings.py — Build vault-wide embeddings con Ollama + sqlite-vec.

Lee todos los .md del vault (excluyendo `.obsidian`, `_meta`, `_trash`, `_archive`),
genera embeddings con `nomic-embed-text` via Ollama, y persiste en SQLite local
con extensión `sqlite-vec`. Idempotente: re-runs solo re-embed lo que cambió.

Notas largas (> CHUNK_THRESHOLD bytes) se parten en chunks con overlap.

Env:
    RUFINO_VAULT_PATH   path absoluto al vault de Obsidian.
    OLLAMA_HOST         default http://localhost:11434.
    OLLAMA_MODEL        default nomic-embed-text.
    EMB_DB              default ${RUFINO_VAULT_PATH}/_meta/embeddings.sqlite.

Uso:
    python3 rufino-build-embeddings.py          # full build (incremental)
    python3 rufino-build-embeddings.py --only <path>  # re-index una sola nota
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import struct
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Iterable

import sqlite_vec

# --------- Config ---------
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "nomic-embed-text")
EMBED_DIM = 768  # nomic-embed-text

CHUNK_THRESHOLD = 4 * 1024  # 4 KB (nomic-embed-text context ~2048 tokens ~6-8KB chars)
CHUNK_SIZE = 3 * 1024  # 3 KB
CHUNK_OVERLAP = 200  # chars

EXCLUDE_DIR_NAMES = {".obsidian", "_meta", "_trash", "_archive"}

FRONTMATTER_RE = re.compile(r"^---\n.*?\n---\n", re.DOTALL)
H1_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)


# --------- Helpers ---------
def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def vault_path() -> Path:
    v = os.environ.get("RUFINO_VAULT_PATH")
    if not v:
        log("ERROR: RUFINO_VAULT_PATH no está seteado.")
        sys.exit(2)
    p = Path(v).expanduser().resolve()
    if not p.is_dir():
        log(f"ERROR: RUFINO_VAULT_PATH no es un directorio válido: {p}")
        sys.exit(2)
    return p


def db_path(vault: Path) -> Path:
    custom = os.environ.get("EMB_DB")
    if custom:
        return Path(custom).expanduser().resolve()
    meta = vault / "_meta"
    meta.mkdir(parents=True, exist_ok=True)
    return meta / "embeddings.sqlite"


def http_post_json(url: str, payload: dict, timeout: float = 120.0) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def http_get_json(url: str, timeout: float = 5.0) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        return None


# --------- Ollama ---------
def ensure_ollama() -> None:
    """Verifica que Ollama esté arriba; si no, intenta levantarlo con `ollama serve`."""
    tags = http_get_json(f"{OLLAMA_HOST}/api/tags")
    if tags is not None:
        return
    log("Ollama no responde. Intentando levantarlo con `ollama serve` en background...")
    import subprocess

    try:
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except FileNotFoundError:
        log("ERROR: no se encontró el binario `ollama`. Instalá Ollama y reintentá.")
        sys.exit(3)
    for _ in range(30):
        time.sleep(0.5)
        if http_get_json(f"{OLLAMA_HOST}/api/tags") is not None:
            log("Ollama listo.")
            return
    log("ERROR: Ollama no levantó en 15s. Levantalo a mano: `ollama serve &`.")
    sys.exit(3)


def ensure_model() -> None:
    """Verifica que el modelo esté disponible; si no, lo pullea."""
    tags = http_get_json(f"{OLLAMA_HOST}/api/tags") or {}
    models = [m.get("name", "").split(":")[0] for m in tags.get("models", [])]
    if OLLAMA_MODEL.split(":")[0] in models:
        return
    log(f"Modelo `{OLLAMA_MODEL}` no presente. Haciendo pull (~270MB)...")
    import subprocess

    r = subprocess.run(["ollama", "pull", OLLAMA_MODEL])
    if r.returncode != 0:
        log(f"ERROR: `ollama pull {OLLAMA_MODEL}` falló.")
        sys.exit(3)


def embed(text: str) -> list[float]:
    """Embed un texto via Ollama. Devuelve vector de EMBED_DIM floats."""
    payload = {"model": OLLAMA_MODEL, "prompt": text}
    resp = http_post_json(f"{OLLAMA_HOST}/api/embeddings", payload)
    vec = resp.get("embedding")
    if not vec or not isinstance(vec, list):
        raise RuntimeError(f"Embedding inválido: {resp}")
    if len(vec) != EMBED_DIM:
        raise RuntimeError(
            f"Dim inesperada: got {len(vec)}, expected {EMBED_DIM}. "
            f"¿Cambió el modelo?"
        )
    return vec


# --------- SQLite ---------
def open_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS notes (
            rowid INTEGER PRIMARY KEY,
            path TEXT UNIQUE NOT NULL,
            mtime INTEGER NOT NULL,
            content_hash TEXT NOT NULL,
            title TEXT,
            chars INTEGER,
            indexed_at INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS notes_vec USING vec0(
            embedding FLOAT[{EMBED_DIM}]
        )
        """
    )
    conn.commit()
    return conn


def vec_blob(vec: list[float]) -> bytes:
    """Empaqueta floats como little-endian f32, formato esperado por sqlite-vec."""
    return struct.pack(f"<{len(vec)}f", *vec)


# --------- Vault walk ---------
def iter_markdown_files(vault: Path) -> Iterable[Path]:
    """Walk recursivo del vault, skipping directorios excluidos en cualquier nivel."""
    for root, dirs, files in os.walk(vault):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIR_NAMES]
        for name in files:
            if name.endswith(".md"):
                yield Path(root) / name


def strip_frontmatter(body: str) -> str:
    return FRONTMATTER_RE.sub("", body, count=1)


def extract_title(body: str, fallback: str) -> str:
    m = H1_RE.search(body)
    if m:
        return m.group(1).strip()
    return fallback


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def chunk_text(text: str) -> list[str]:
    """Chunking por chars con overlap. Si entra en threshold, un solo chunk."""
    if len(text) <= CHUNK_THRESHOLD:
        return [text]
    chunks = []
    step = CHUNK_SIZE - CHUNK_OVERLAP
    start = 0
    while start < len(text):
        end = min(start + CHUNK_SIZE, len(text))
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start += step
    return chunks


# --------- Build ---------
def build(vault: Path, db: Path, only_path: str | None = None) -> int:
    log(f"vault={vault}")
    log(f"db={db}")
    log(f"model={OLLAMA_MODEL} host={OLLAMA_HOST}")

    ensure_ollama()
    ensure_model()

    conn = open_db(db)
    cur = conn.cursor()

    if only_path:
        target = Path(only_path).expanduser().resolve()
        if not target.is_file():
            log(f"ERROR: archivo no existe: {target}")
            return 4
        try:
            target.relative_to(vault)
        except ValueError:
            log(f"ERROR: {target} no está bajo el vault {vault}.")
            return 4
        paths = [target]
    else:
        paths = sorted(iter_markdown_files(vault))

    log(f"candidates={len(paths)}")

    indexed = 0
    skipped = 0
    errors = 0
    t0 = time.time()

    for fp in paths:
        try:
            rel = str(fp.relative_to(vault))
            stat = fp.stat()
            mtime = int(stat.st_mtime)

            raw = fp.read_text(encoding="utf-8", errors="replace")
            body = strip_frontmatter(raw).strip()
            if not body:
                skipped += 1
                continue

            chash = content_hash(body)
            title = extract_title(body, fp.stem)
            chars = len(body)
            chunks = chunk_text(body)

            # Idempotencia: si chunk-0 (o nota entera) ya está con el mismo hash, skip.
            probe_path = f"{rel}#chunk-0" if len(chunks) > 1 else rel
            row = cur.execute(
                "SELECT content_hash FROM notes WHERE path = ?", (probe_path,)
            ).fetchone()
            if row and row[0] == chash:
                skipped += 1
                continue

            # Borrar entries previas (chunked o no).
            old_rows = cur.execute(
                "SELECT rowid FROM notes WHERE path = ? OR path LIKE ?",
                (rel, f"{rel}#chunk-%"),
            ).fetchall()
            for (old_rowid,) in old_rows:
                cur.execute("DELETE FROM notes_vec WHERE rowid = ?", (old_rowid,))
                cur.execute("DELETE FROM notes WHERE rowid = ?", (old_rowid,))

            now = int(time.time())
            if len(chunks) == 1:
                vec = embed(chunks[0])
                cur.execute(
                    "INSERT INTO notes(path, mtime, content_hash, title, chars, indexed_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (rel, mtime, chash, title, chars, now),
                )
                new_rowid = cur.lastrowid
                cur.execute(
                    "INSERT INTO notes_vec(rowid, embedding) VALUES (?, ?)",
                    (new_rowid, vec_blob(vec)),
                )
            else:
                for i, c in enumerate(chunks):
                    vec = embed(c)
                    cpath = f"{rel}#chunk-{i}"
                    cur.execute(
                        "INSERT INTO notes(path, mtime, content_hash, title, chars, indexed_at) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (cpath, mtime, chash, title, len(c), now),
                    )
                    new_rowid = cur.lastrowid
                    cur.execute(
                        "INSERT INTO notes_vec(rowid, embedding) VALUES (?, ?)",
                        (new_rowid, vec_blob(vec)),
                    )
            conn.commit()
            indexed += 1
            if indexed % 25 == 0:
                elapsed = time.time() - t0
                log(f"  [{indexed}] {rel}  ({elapsed:.1f}s)")
        except Exception as e:  # noqa: BLE001
            errors += 1
            log(f"  ERR {fp}: {e}")
            try:
                conn.rollback()
            except sqlite3.Error:
                pass

    elapsed = time.time() - t0
    total_rows = cur.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
    db_size = db.stat().st_size if db.exists() else 0

    log("")
    log(
        f"indexed={indexed} skipped={skipped} errors={errors} "
        f"elapsed={elapsed:.1f}s"
    )
    log(f"db_rows={total_rows} db_size={db_size} bytes")

    conn.close()
    return 0 if errors == 0 else 1


def main(argv: list[str]) -> int:
    only_path = None
    if "--only" in argv:
        idx = argv.index("--only")
        if idx + 1 >= len(argv):
            log("Uso: --only <path-a-md>")
            return 2
        only_path = argv[idx + 1]
    return build(vault_path(), db_path(vault_path()), only_path)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
