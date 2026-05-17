# Plan 7 — Query layer + MCP server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementar la primitive Query layer con sus 3 backends (lexical via ripgrep, semántico via Ollama + sqlite-vec, grafo via triple store SQLite) detrás de una API unificada. Más el MCP server `ask-rufino` que expone 6 tools al Claude Code anfitrión.

**Architecture:** `QueryLayer` es una clase facade que delega en backends según el `mode` solicitado. Backends son lazy: lexical no requiere index, semántico construye on-demand desde frontmatter, grafo se rebuild desde frontmatter `triples:`. El MCP server es un proceso stdio que importa la QueryLayer y expone tools usando `mcp` package.

**Tech Stack:** Python 3.11+, ripgrep (CLI), sqlite-vec, ollama (cliente HTTP local), `mcp` package (Anthropic).

**Dependencias previas:** Plan 1, Plan 3 (StubQueryLayer reemplazado).

**Plans que dependen de este:** Plan 8 (Wizard puede consultar vault), Plan 5 (Output dispatcher con query real).

---

## File Structure

```
src/rufino/engine/query/
├── __init__.py
├── api.py                  # QueryLayer facade
├── lexical.py              # LexicalBackend (ripgrep)
├── semantic.py             # SemanticBackend (Ollama + sqlite-vec)
├── graph.py                # GraphBackend (triple store SQLite)
└── note_ref.py             # NoteRef dataclass
src/rufino/mcp_server/
├── __init__.py
├── server.py               # MCP server entry (stdio)
└── tools.py                # 6 tools exposed
src/rufino/cli.py           # MODIFY: `rufino query` + `rufino mcp-server`
tests/test_query_*.py
tests/test_mcp_*.py
```

---

## Task 1: NoteRef + lexical backend

**Files:**
- Create: `src/rufino/engine/query/__init__.py`
- Create: `src/rufino/engine/query/note_ref.py`
- Create: `src/rufino/engine/query/lexical.py`
- Create: `tests/test_query_lexical.py`

- [ ] **Step 1: Failing test**

`tests/test_query_lexical.py`:
```python
from pathlib import Path
from rufino.engine.query.lexical import LexicalBackend
from rufino.engine.query.note_ref import NoteRef


def test_lexical_finds_word_across_notes(tmp_vault: Path):
    (tmp_vault / "a.md").write_text("regresión logística estudio")
    (tmp_vault / "b.md").write_text("svm y trees")
    (tmp_vault / "c.md").write_text("notes about regresión lineal")

    backend = LexicalBackend(vault_root=tmp_vault)
    results = backend.search("regresión")
    paths = sorted(r.relative_path for r in results)
    assert "a.md" in paths
    assert "c.md" in paths
    assert "b.md" not in paths


def test_lexical_returns_empty_when_no_match(tmp_vault: Path):
    (tmp_vault / "a.md").write_text("hello")
    backend = LexicalBackend(vault_root=tmp_vault)
    assert backend.search("nonexistent_xyz") == []
```

- [ ] **Step 2: Run (fails)**

- [ ] **Step 3: Implement**

`src/rufino/engine/query/__init__.py`: `` (empty)

`src/rufino/engine/query/note_ref.py`:
```python
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class NoteRef:
    relative_path: str  # relative to vault root
    score: float = 1.0  # ranking score; 1.0 if not applicable
```

`src/rufino/engine/query/lexical.py`:
```python
import subprocess
from dataclasses import dataclass
from pathlib import Path

from rufino.engine.query.note_ref import NoteRef


@dataclass
class LexicalBackend:
    vault_root: Path

    def search(self, query: str) -> list[NoteRef]:
        try:
            completed = subprocess.run(
                ["rg", "-l", "--type", "md", query, str(self.vault_root)],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
        except FileNotFoundError:
            # ripgrep not installed → fall back to Python grep
            return self._python_fallback(query)

        if completed.returncode == 1:  # no matches
            return []
        if completed.returncode != 0:
            raise RuntimeError(f"ripgrep failed: {completed.stderr}")

        return [
            NoteRef(relative_path=str(Path(line).relative_to(self.vault_root)))
            for line in completed.stdout.splitlines()
        ]

    def _python_fallback(self, query: str) -> list[NoteRef]:
        results: list[NoteRef] = []
        for p in self.vault_root.rglob("*.md"):
            if query.lower() in p.read_text().lower():
                results.append(
                    NoteRef(relative_path=str(p.relative_to(self.vault_root)))
                )
        return results
```

- [ ] **Step 4: Run tests** — Expected: 2 passed (uses fallback if rg absent)

- [ ] **Step 5: Commit**

```bash
git add src/rufino/engine/query/__init__.py src/rufino/engine/query/note_ref.py src/rufino/engine/query/lexical.py tests/test_query_lexical.py
git commit -m "feat(query): LexicalBackend with ripgrep + Python fallback"
```

---

## Task 2: Graph backend (triple store)

**Files:**
- Create: `src/rufino/engine/query/graph.py`
- Create: `tests/test_query_graph.py`

- [ ] **Step 1: Failing test**

`tests/test_query_graph.py`:
```python
from pathlib import Path
from rufino.engine.query.graph import GraphBackend


def test_extracts_triples_from_frontmatter_and_traverses(tmp_vault: Path):
    (tmp_vault / "clase1.md").write_text(
        "---\ntriples:\n  - { r: tema-de, o: ml-i }\n  - { r: expuesto-por, o: mendez }\n---\nB\n"
    )
    (tmp_vault / "clase2.md").write_text(
        "---\ntriples:\n  - { r: tema-de, o: ml-i }\n---\nB\n"
    )

    backend = GraphBackend(vault_root=tmp_vault)
    backend.rebuild_index()

    related = backend.traverse(node="ml-i", relation="tema-de", depth=1, reverse=True)
    relative_paths = sorted(r.relative_path for r in related)
    assert "clase1.md" in relative_paths
    assert "clase2.md" in relative_paths


def test_no_triples_returns_empty(tmp_vault: Path):
    (tmp_vault / "n.md").write_text("plain note no frontmatter")
    backend = GraphBackend(vault_root=tmp_vault)
    backend.rebuild_index()
    assert backend.traverse(node="x", relation="r", depth=1) == []
```

- [ ] **Step 2: Run (fails)**

- [ ] **Step 3: Implement**

`src/rufino/engine/query/graph.py`:
```python
import sqlite3
from dataclasses import dataclass
from pathlib import Path
import yaml

from rufino.engine.query.note_ref import NoteRef


@dataclass
class GraphBackend:
    vault_root: Path

    def __post_init__(self) -> None:
        self._db_path = self.vault_root / "_meta" / "triples.sqlite"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS triples ("
            "subject_path TEXT, relation TEXT, object TEXT, "
            "PRIMARY KEY(subject_path, relation, object))"
        )

    def rebuild_index(self) -> None:
        self._conn.execute("DELETE FROM triples")
        for p in self.vault_root.rglob("*.md"):
            text = p.read_text()
            if not text.startswith("---\n"):
                continue
            try:
                _, fm_block, _ = text.split("---\n", 2)
            except ValueError:
                continue
            fm = yaml.safe_load(fm_block) or {}
            triples = fm.get("triples", [])
            if not isinstance(triples, list):
                continue
            rel_path = str(p.relative_to(self.vault_root))
            for entry in triples:
                if isinstance(entry, dict) and "r" in entry and "o" in entry:
                    self._conn.execute(
                        "INSERT OR IGNORE INTO triples VALUES (?, ?, ?)",
                        (rel_path, entry["r"], entry["o"]),
                    )
        self._conn.commit()

    def traverse(
        self,
        *,
        node: str,
        relation: str,
        depth: int,
        reverse: bool = False,
    ) -> list[NoteRef]:
        """Find notes connected to `node` via `relation`.

        depth=1 only (multi-hop deferred to v1.1).
        reverse=True: find notes whose triple POINTS TO `node` (inbound).
        reverse=False: find objects of triples FROM `node` (outbound).
        """
        if reverse:
            cur = self._conn.execute(
                "SELECT subject_path FROM triples WHERE relation = ? AND object = ?",
                (relation, node),
            )
            return [NoteRef(relative_path=row[0]) for row in cur.fetchall()]
        # Outbound: would need to know the subject_path = node → not 1:1 with notes
        # In v1 we only support reverse traversal (most common use)
        return []
```

- [ ] **Step 4: Run tests** — Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/rufino/engine/query/graph.py tests/test_query_graph.py
git commit -m "feat(query): GraphBackend with SQLite triple store + reverse traversal"
```

---

## Task 3: Semantic backend (Ollama + sqlite-vec) — with offline mode fallback

**Files:**
- Create: `src/rufino/engine/query/semantic.py`
- Create: `tests/test_query_semantic.py`

- [ ] **Step 1: Failing test**

`tests/test_query_semantic.py`:
```python
import pytest
from pathlib import Path
from rufino.engine.query.semantic import SemanticBackend, EmbeddingProvider


class FakeEmbeddings:
    """Deterministic fake embeddings: hash(text) → 8-dim vector."""
    def embed(self, text: str) -> list[float]:
        import hashlib
        h = hashlib.sha256(text.encode()).digest()[:8]
        return [b / 255.0 for b in h]


def test_index_and_search_with_fake_embeddings(tmp_vault: Path):
    (tmp_vault / "a.md").write_text("ml regression")
    (tmp_vault / "b.md").write_text("svm trees")

    backend = SemanticBackend(vault_root=tmp_vault, embedder=FakeEmbeddings())
    backend.rebuild_index()

    results = backend.search("ml regression", k=2)
    assert len(results) == 2
    # First result should be the closest (the same text); since hashes are pseudo-random
    # we don't assert specific ordering — just that both notes are returned.
    paths = sorted(r.relative_path for r in results)
    assert "a.md" in paths
    assert "b.md" in paths


def test_empty_vault_returns_empty(tmp_vault: Path):
    backend = SemanticBackend(vault_root=tmp_vault, embedder=FakeEmbeddings())
    backend.rebuild_index()
    assert backend.search("anything", k=5) == []
```

- [ ] **Step 2: Run (fails)**

- [ ] **Step 3: Implement (using stdlib only — sqlite-vec optional)**

`src/rufino/engine/query/semantic.py`:
```python
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from rufino.engine.query.note_ref import NoteRef


class EmbeddingProvider(Protocol):
    def embed(self, text: str) -> list[float]: ...


@dataclass
class SemanticBackend:
    """Semantic search via embeddings.

    v1 uses a simple cosine-similarity in pure Python over a SQLite-stored vector list.
    sqlite-vec integration is a v1.1 optimization that doesn't change the API.
    """
    vault_root: Path
    embedder: EmbeddingProvider

    def __post_init__(self) -> None:
        self._db_path = self.vault_root / "_meta" / "embeddings.sqlite"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS notes "
            "(rel_path TEXT PRIMARY KEY, vector TEXT)"
        )

    def rebuild_index(self) -> None:
        self._conn.execute("DELETE FROM notes")
        for p in self.vault_root.rglob("*.md"):
            text = p.read_text()
            vec = self.embedder.embed(text)
            rel = str(p.relative_to(self.vault_root))
            self._conn.execute(
                "INSERT OR REPLACE INTO notes VALUES (?, ?)",
                (rel, json.dumps(vec)),
            )
        self._conn.commit()

    def search(self, query: str, *, k: int) -> list[NoteRef]:
        q_vec = self.embedder.embed(query)
        cur = self._conn.execute("SELECT rel_path, vector FROM notes")
        scored: list[tuple[str, float]] = []
        for rel, vec_json in cur.fetchall():
            vec = json.loads(vec_json)
            scored.append((rel, _cosine(q_vec, vec)))
        scored.sort(key=lambda x: x[1], reverse=True)
        return [NoteRef(relative_path=p, score=s) for p, s in scored[:k]]


def _cosine(a: list[float], b: list[float]) -> float:
    import math
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1e-9
    nb = math.sqrt(sum(y * y for y in b)) or 1e-9
    return dot / (na * nb)
```

- [ ] **Step 4: Run tests** — Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/rufino/engine/query/semantic.py tests/test_query_semantic.py
git commit -m "feat(query): SemanticBackend with cosine similarity (sqlite-vec deferred)"
```

---

## Task 4: Unified QueryLayer facade

**Files:**
- Create: `src/rufino/engine/query/api.py`
- Create: `tests/test_query_api.py`

- [ ] **Step 1: Failing test**

`tests/test_query_api.py`:
```python
from pathlib import Path
from rufino.engine.query.api import QueryLayer
from rufino.engine.query.semantic import EmbeddingProvider


class FakeEmbeddings:
    def embed(self, text: str) -> list[float]:
        import hashlib
        h = hashlib.sha256(text.encode()).digest()[:8]
        return [b / 255.0 for b in h]


def test_search_lexical_mode(tmp_vault: Path):
    (tmp_vault / "x.md").write_text("regresion logistica")
    ql = QueryLayer(vault_root=tmp_vault, embedder=FakeEmbeddings())
    ql.rebuild_indices()
    results = ql.search("regresion", mode="lexical")
    assert any(r.relative_path == "x.md" for r in results)


def test_search_semantic_mode(tmp_vault: Path):
    (tmp_vault / "x.md").write_text("svm")
    ql = QueryLayer(vault_root=tmp_vault, embedder=FakeEmbeddings())
    ql.rebuild_indices()
    results = ql.search("svm", mode="semantic")
    assert len(results) == 1


def test_traverse_via_graph(tmp_vault: Path):
    (tmp_vault / "c.md").write_text(
        "---\ntriples:\n  - { r: tema-de, o: ml-i }\n---\nbody\n"
    )
    ql = QueryLayer(vault_root=tmp_vault, embedder=FakeEmbeddings())
    ql.rebuild_indices()
    results = ql.traverse(node="ml-i", relation="tema-de", depth=1, reverse=True)
    assert any(r.relative_path == "c.md" for r in results)


def test_invalid_mode_raises(tmp_vault: Path):
    import pytest
    ql = QueryLayer(vault_root=tmp_vault, embedder=FakeEmbeddings())
    with pytest.raises(ValueError):
        ql.search("x", mode="bogus")
```

- [ ] **Step 2: Run (fails)**

- [ ] **Step 3: Implement**

`src/rufino/engine/query/api.py`:
```python
from dataclasses import dataclass
from pathlib import Path

from rufino.engine.query.note_ref import NoteRef
from rufino.engine.query.lexical import LexicalBackend
from rufino.engine.query.semantic import SemanticBackend, EmbeddingProvider
from rufino.engine.query.graph import GraphBackend


VALID_MODES = {"lexical", "semantic", "hybrid"}


@dataclass
class QueryLayer:
    vault_root: Path
    embedder: EmbeddingProvider

    def __post_init__(self) -> None:
        self._lex = LexicalBackend(vault_root=self.vault_root)
        self._sem = SemanticBackend(vault_root=self.vault_root, embedder=self.embedder)
        self._graph = GraphBackend(vault_root=self.vault_root)

    def rebuild_indices(self) -> None:
        self._sem.rebuild_index()
        self._graph.rebuild_index()
        # Lexical (ripgrep) is index-free

    def search(self, query: str, *, mode: str = "hybrid", k: int = 10) -> list[NoteRef]:
        if mode not in VALID_MODES:
            raise ValueError(f"mode must be in {VALID_MODES}, got {mode!r}")
        if mode == "lexical":
            return self._lex.search(query)
        if mode == "semantic":
            return self._sem.search(query, k=k)
        # hybrid: union of both, ranked by best score
        lex = self._lex.search(query)
        sem = self._sem.search(query, k=k)
        seen: dict[str, NoteRef] = {}
        for r in sem + lex:
            existing = seen.get(r.relative_path)
            if existing is None or r.score > existing.score:
                seen[r.relative_path] = r
        return sorted(seen.values(), key=lambda r: r.score, reverse=True)[:k]

    def traverse(
        self, *, node: str, relation: str, depth: int, reverse: bool = False,
    ) -> list[NoteRef]:
        return self._graph.traverse(node=node, relation=relation, depth=depth, reverse=reverse)
```

- [ ] **Step 4: Run tests** — Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/rufino/engine/query/api.py tests/test_query_api.py
git commit -m "feat(query): unified QueryLayer facade (search + traverse)"
```

---

## Task 5: MCP server with 6 tools

**Files:**
- Create: `src/rufino/mcp_server/__init__.py`
- Create: `src/rufino/mcp_server/tools.py`
- Create: `src/rufino/mcp_server/server.py`
- Create: `tests/test_mcp_tools.py`

- [ ] **Step 1: Failing test (test tools as pure functions, no MCP wire)**

`tests/test_mcp_tools.py`:
```python
from pathlib import Path
from rufino.mcp_server.tools import (
    search_vault, find_note, list_triples_for_node,
    read_note, vault_stats, list_recent_notes,
)
from rufino.engine.query.api import QueryLayer


class FakeEmbeddings:
    def embed(self, text):
        import hashlib
        h = hashlib.sha256(text.encode()).digest()[:8]
        return [b / 255.0 for b in h]


def _make_ql(vault: Path) -> QueryLayer:
    ql = QueryLayer(vault_root=vault, embedder=FakeEmbeddings())
    ql.rebuild_indices()
    return ql


def test_search_vault_returns_paths(tmp_vault: Path):
    (tmp_vault / "x.md").write_text("regresion logistica")
    ql = _make_ql(tmp_vault)
    result = search_vault(ql, query="regresion", mode="lexical")
    assert "x.md" in result


def test_read_note_returns_content(tmp_vault: Path):
    (tmp_vault / "a.md").write_text("content here")
    ql = _make_ql(tmp_vault)
    assert read_note(ql, relative_path="a.md") == "content here"


def test_read_note_rejects_path_traversal(tmp_vault: Path):
    ql = _make_ql(tmp_vault)
    import pytest
    with pytest.raises(ValueError, match="outside"):
        read_note(ql, relative_path="../etc/passwd")


def test_vault_stats_reports_count(tmp_vault: Path):
    (tmp_vault / "a.md").write_text("x")
    (tmp_vault / "b.md").write_text("y")
    ql = _make_ql(tmp_vault)
    stats = vault_stats(ql)
    assert stats["note_count"] == 2


def test_list_recent_notes(tmp_vault: Path):
    import time
    (tmp_vault / "a.md").write_text("old")
    time.sleep(0.01)
    (tmp_vault / "b.md").write_text("new")
    ql = _make_ql(tmp_vault)
    recent = list_recent_notes(ql, k=2)
    assert recent[0] == "b.md"


def test_list_triples_for_node(tmp_vault: Path):
    (tmp_vault / "c.md").write_text(
        "---\ntriples:\n  - { r: tema-de, o: ml-i }\n---\nbody\n"
    )
    ql = _make_ql(tmp_vault)
    results = list_triples_for_node(ql, node="ml-i", relation="tema-de", reverse=True)
    assert "c.md" in results
```

- [ ] **Step 2: Run (fails)**

- [ ] **Step 3: Implement**

`src/rufino/mcp_server/__init__.py`: `` (empty)

`src/rufino/mcp_server/tools.py`:
```python
from pathlib import Path
from rufino.engine.query.api import QueryLayer


def search_vault(ql: QueryLayer, *, query: str, mode: str = "hybrid", k: int = 10) -> list[str]:
    results = ql.search(query, mode=mode, k=k)
    return [r.relative_path for r in results]


def find_note(ql: QueryLayer, *, query: str) -> str | None:
    results = ql.search(query, mode="hybrid", k=1)
    return results[0].relative_path if results else None


def list_triples_for_node(
    ql: QueryLayer, *, node: str, relation: str, reverse: bool = True,
) -> list[str]:
    results = ql.traverse(node=node, relation=relation, depth=1, reverse=reverse)
    return [r.relative_path for r in results]


def read_note(ql: QueryLayer, *, relative_path: str) -> str:
    target = (ql.vault_root / relative_path).resolve()
    vault_resolved = ql.vault_root.resolve()
    try:
        target.relative_to(vault_resolved)
    except ValueError:
        raise ValueError(f"Path {relative_path!r} resolves outside vault")
    return target.read_text()


def vault_stats(ql: QueryLayer) -> dict:
    notes = list(ql.vault_root.rglob("*.md"))
    return {
        "note_count": len(notes),
        "vault_path": str(ql.vault_root),
    }


def list_recent_notes(ql: QueryLayer, *, k: int = 10) -> list[str]:
    notes = list(ql.vault_root.rglob("*.md"))
    notes.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [str(p.relative_to(ql.vault_root)) for p in notes[:k]]
```

- [ ] **Step 4: Run tests** — Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/rufino/mcp_server/__init__.py src/rufino/mcp_server/tools.py tests/test_mcp_tools.py
git commit -m "feat(mcp): 6 tools (search/find/triples/read/stats/recent)"
```

---

## Task 6: MCP server stdio wire (using `mcp` package)

**Files:**
- Create: `src/rufino/mcp_server/server.py`
- Modify: `src/rufino/cli.py`
- Create: `tests/test_mcp_server_smoke.py`

- [ ] **Step 1: Add MCP package dep**

Modify `pyproject.toml`:
```toml
dependencies = [
    "click>=8.1",
    "pyyaml>=6.0",
    "keyring>=24.0",
    "jinja2>=3.1",
    "mcp>=0.5",
]
```

Run: `pip install -e ".[dev]"`

- [ ] **Step 2: Smoke test (lightweight — verifies server module loads + tools wire)**

`tests/test_mcp_server_smoke.py`:
```python
from pathlib import Path
from rufino.mcp_server.server import build_server
from rufino.engine.query.api import QueryLayer


class FakeEmbeddings:
    def embed(self, text):
        return [0.0] * 8


def test_server_builds_with_query_layer(tmp_vault: Path):
    ql = QueryLayer(vault_root=tmp_vault, embedder=FakeEmbeddings())
    server = build_server(ql)
    # build_server should return an MCP Server instance; we only assert non-None here.
    # Full stdio wire test requires running the MCP client harness — deferred to integration tests.
    assert server is not None
```

- [ ] **Step 3: Implement server**

`src/rufino/mcp_server/server.py`:
```python
from rufino.engine.query.api import QueryLayer
from rufino.mcp_server import tools as t


def build_server(ql: QueryLayer):
    """Build an MCP Server registering the 6 ask-rufino tools.

    The actual MCP runtime wire (stdio_server, tool registration syntax) varies
    by version of the `mcp` package. This function returns a configured server
    object that the CLI can run via `server.run_stdio_async()`.
    """
    from mcp.server import Server
    from mcp.types import Tool, TextContent

    server = Server("ask-rufino")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(name="search_vault", description="Search the vault by query",
                 inputSchema={"type": "object", "properties": {"query": {"type": "string"}}}),
            Tool(name="find_note", description="Find single best matching note",
                 inputSchema={"type": "object", "properties": {"query": {"type": "string"}}}),
            Tool(name="list_triples_for_node", description="Find notes related to a node",
                 inputSchema={"type": "object", "properties": {
                     "node": {"type": "string"}, "relation": {"type": "string"}}}),
            Tool(name="read_note", description="Read a note by relative path",
                 inputSchema={"type": "object", "properties": {"relative_path": {"type": "string"}}}),
            Tool(name="vault_stats", description="Get vault statistics",
                 inputSchema={"type": "object", "properties": {}}),
            Tool(name="list_recent_notes", description="List N most recent notes",
                 inputSchema={"type": "object", "properties": {"k": {"type": "integer"}}}),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        if name == "search_vault":
            result = t.search_vault(ql, **arguments)
        elif name == "find_note":
            result = t.find_note(ql, **arguments)
        elif name == "list_triples_for_node":
            result = t.list_triples_for_node(ql, **arguments)
        elif name == "read_note":
            result = t.read_note(ql, **arguments)
        elif name == "vault_stats":
            result = t.vault_stats(ql)
        elif name == "list_recent_notes":
            result = t.list_recent_notes(ql, **arguments)
        else:
            raise ValueError(f"Unknown tool: {name}")

        import json
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    return server
```

- [ ] **Step 4: Append CLI command**

Append to `src/rufino/cli.py`:
```python
from rufino.engine.query.api import QueryLayer
from rufino.mcp_server.server import build_server


class _NoopEmbeddings:
    """Placeholder embedder for v1. Real Ollama wiring lands in plan 9 installer."""
    def embed(self, text: str) -> list[float]:
        return [0.0] * 8


@cli.command(name="query")
@click.argument("query_string")
@click.option("--vault", "vault_root", required=True, type=click.Path(path_type=Path))
@click.option("--mode", default="hybrid", type=click.Choice(["lexical", "semantic", "hybrid"]))
def query_cmd(query_string: str, vault_root: Path, mode: str) -> None:
    """Search the vault."""
    ql = QueryLayer(vault_root=vault_root, embedder=_NoopEmbeddings())
    if mode != "lexical":
        ql.rebuild_indices()
    results = ql.search(query_string, mode=mode)
    for r in results:
        click.echo(r.relative_path)


@cli.command(name="mcp-server")
@click.option("--vault", "vault_root", required=True, type=click.Path(path_type=Path))
def mcp_server_cmd(vault_root: Path) -> None:
    """Run the ask-rufino MCP server on stdio."""
    import asyncio
    from mcp.server.stdio import stdio_server

    ql = QueryLayer(vault_root=vault_root, embedder=_NoopEmbeddings())
    server = build_server(ql)

    async def _main():
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    asyncio.run(_main())
```

- [ ] **Step 5: Run smoke test** — Expected: 1 passed

Run: `pytest tests/test_mcp_server_smoke.py -v`

- [ ] **Step 6: Run full suite**

Run: `pytest -v` — all pass

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml src/rufino/mcp_server/server.py src/rufino/cli.py tests/test_mcp_server_smoke.py
git commit -m "feat(mcp): stdio MCP server with 6 ask-rufino tools + CLI"
```

---

## Self-review checklist

- [ ] LexicalBackend falls back to Python grep when ripgrep absent
- [ ] GraphBackend rebuilds idempotently
- [ ] SemanticBackend cosine returns 1.0 for identical vectors (within float precision)
- [ ] QueryLayer hybrid de-duplicates by relative_path
- [ ] MCP tool read_note rejects `../` path traversal
- [ ] MCP server registers exactly 6 tools matching the spec
- [ ] CLI `rufino query` works in lexical mode without Ollama running

## Done criteria

- `pytest tests/test_query_*.py tests/test_mcp_*.py -v` all pass
- `./cli/rufino query "regresion" --vault X --mode lexical` returns matching paths
- `./cli/rufino mcp-server --vault X` runs without crashing (Ctrl+C to exit)
