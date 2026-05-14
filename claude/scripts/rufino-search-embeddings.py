#!/usr/bin/env python3
"""
rufino-search-embeddings.py — Búsqueda semántica sobre embeddings del vault.

Embebe la query con Ollama (mismo modelo que el build) y consulta SQLite con
`vec_distance_cosine` vía la virtual table de sqlite-vec.

Usage:
    rufino-search-embeddings.py "<query>" [-k N]
    rufino-search-embeddings.py "<query>" --json
"""

from __future__ import annotations

import json
import os
import struct
import sqlite3
import sys
import urllib.request
from pathlib import Path

import sqlite_vec

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "nomic-embed-text")
EMBED_DIM = 768
DEFAULT_K = 10


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def vault_path() -> Path:
    v = os.environ.get("RUFINO_VAULT_PATH")
    if not v:
        log("ERROR: RUFINO_VAULT_PATH no está seteado.")
        sys.exit(2)
    return Path(v).expanduser().resolve()


def db_path(vault: Path) -> Path:
    custom = os.environ.get("EMB_DB")
    if custom:
        return Path(custom).expanduser().resolve()
    return vault / "_meta" / "embeddings.sqlite"


def embed(text: str) -> list[float]:
    payload = json.dumps({"model": OLLAMA_MODEL, "prompt": text}).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA_HOST}/api/embeddings",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    vec = body.get("embedding")
    if not vec or len(vec) != EMBED_DIM:
        raise RuntimeError(f"Embedding inválido: {body}")
    return vec


def vec_blob(vec: list[float]) -> bytes:
    return struct.pack(f"<{len(vec)}f", *vec)


def search(query: str, k: int, as_json: bool) -> int:
    vault = vault_path()
    db = db_path(vault)
    if not db.exists():
        log(f"ERROR: DB no existe: {db}. Corré rufino-build-embeddings.sh primero.")
        return 3

    qvec = embed(query)

    conn = sqlite3.connect(str(db))
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)

    rows = conn.execute(
        """
        SELECT n.path, n.title, v.distance
        FROM notes_vec v
        JOIN notes n ON n.rowid = v.rowid
        WHERE v.embedding MATCH ? AND k = ?
        ORDER BY v.distance
        """,
        (vec_blob(qvec), k),
    ).fetchall()
    conn.close()

    if as_json:
        out = [
            {"distance": round(dist, 4), "path": path, "title": title}
            for (path, title, dist) in rows
        ]
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    for path, title, dist in rows:
        print(f"{dist:.4f}  {path}  —  {title}")
    return 0


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        log('Uso: rufino-search-embeddings.py "<query>" [-k N] [--json]')
        return 2
    query = argv[0]
    k = DEFAULT_K
    as_json = False
    i = 1
    while i < len(argv):
        a = argv[i]
        if a == "-k" and i + 1 < len(argv):
            k = int(argv[i + 1])
            i += 2
        elif a == "--json":
            as_json = True
            i += 1
        else:
            log(f"Argumento desconocido: {a}")
            return 2
    return search(query, k, as_json)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
