#!/usr/bin/env python3
"""
Rufino — Cross-source person resolver (Fase 4).

Lee todos los `_people/<slug>.md` del vault, detecta posibles duplicados
con string similarity (Levenshtein + Jaccard + slug match) y genera notas
en `${RUFINO_VAULT_PATH}/questions/person-resolution-<a>-vs-<b>.md` para
que Val confirme manualmente.

NO mergea nada automáticamente. NO depende de embeddings. Es solo un
first-cut sobre similaridad textual de nombres y slugs.

Uso:
    rufino-person-resolver.py               # genera questions reales
    rufino-person-resolver.py --dry-run     # solo imprime, no escribe

Variables de entorno:
    RUFINO_VAULT_PATH    obligatorio. Ej: /Users/val/Files/vaultlentino
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from itertools import combinations
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# Tuning
# ─────────────────────────────────────────────────────────────────────────────

THRESHOLD_MEDIUM = 0.60
THRESHOLD_HIGH = 0.85

WEIGHTS = {
    "name_levenshtein": 0.40,
    "name_jaccard": 0.20,
    "slug_similarity": 0.20,
    "subset_bonus": 0.20,
}

CREATED_BY = "rufino-person-resolver"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers — string similarity
# ─────────────────────────────────────────────────────────────────────────────

def normalize(text: str) -> str:
    """lowercase + strip accents (NFD + filter Mn) + collapse whitespace."""
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFD", text)
    no_accents = "".join(c for c in nfkd if unicodedata.category(c) != "Mn")
    lowered = no_accents.lower().strip()
    return re.sub(r"\s+", " ", lowered)


def levenshtein(a: str, b: str) -> int:
    """Iterative Levenshtein distance — O(len(a) * len(b)) time, O(len(b)) space."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            cur.append(min(
                cur[-1] + 1,           # insertion
                prev[j] + 1,           # deletion
                prev[j - 1] + cost,    # substitution
            ))
        prev = cur
    return prev[-1]


def lev_ratio(a: str, b: str) -> float:
    """1 - dist / max_len. 1.0 = idénticos, 0.0 = totalmente distintos."""
    if not a and not b:
        return 1.0
    max_len = max(len(a), len(b))
    if max_len == 0:
        return 1.0
    return 1.0 - (levenshtein(a, b) / max_len)


def tokens(name: str) -> set[str]:
    """Tokenize por whitespace/-/_, ignorando tokens de 1 char."""
    norm = normalize(name)
    raw = re.split(r"[\s\-_]+", norm)
    return {t for t in raw if len(t) > 1}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def slug_similarity(slug_a: str, slug_b: str) -> float:
    """Combo de prefix, containment y levenshtein sobre slugs (no acentos por
    construcción de slug). Devuelve max de las 3 señales en [0, 1]."""
    a = slug_a.lower()
    b = slug_b.lower()
    if a == b:
        return 1.0
    # Prefix bonus: si comparten prefijo significativo (>=3 chars y >=50% del corto).
    shortest, longest = (a, b) if len(a) <= len(b) else (b, a)
    common = 0
    for x, y in zip(a, b):
        if x == y:
            common += 1
        else:
            break
    prefix = 0.0
    if common >= 3 and common >= len(shortest) * 0.5:
        prefix = common / len(longest)
    # Containment.
    contain = 1.0 if (shortest in longest) else 0.0
    # Levenshtein.
    lev = lev_ratio(a, b)
    return max(prefix, contain, lev)


def is_subset(name_a: str, name_b: str) -> bool:
    """True si un nombre (normalized) está contenido como substring del otro,
    o si todos los tokens >1char de un nombre están en el otro."""
    na, nb = normalize(name_a), normalize(name_b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    # substring directo (ej "diego" vs "diego diseñador").
    if na in nb or nb in na:
        return True
    ta, tb = tokens(name_a), tokens(name_b)
    if not ta or not tb:
        return False
    # Todos los tokens del más corto están en el más largo.
    short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    return short.issubset(long_)


# ─────────────────────────────────────────────────────────────────────────────
# Vault model
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Person:
    slug: str
    path: Path
    display_name: str
    sources: list[str] = field(default_factory=list)
    referenced_in: int = 0


FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
H1_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)


def parse_frontmatter(text: str) -> dict[str, object]:
    """Mini parser ad hoc — solo lo que necesitamos.
    Soporta scalares simples y listas de items con guion."""
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}
    body = m.group(1)
    result: dict[str, object] = {}
    lines = body.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        # Top-level key: indent 0.
        if line[0] in " \t":
            i += 1
            continue
        if ":" not in line:
            i += 1
            continue
        key, _, rest = line.partition(":")
        key = key.strip()
        rest = rest.strip()
        if rest:
            # Scalar inline (puede tener comillas).
            value = rest.strip('"').strip("'")
            result[key] = value
            i += 1
            continue
        # Lookahead: ¿lista con guiones?
        items: list[str] = []
        j = i + 1
        while j < len(lines) and (lines[j].startswith("  -") or lines[j].startswith("\t-")):
            item = lines[j].split("-", 1)[1].strip().strip('"').strip("'")
            items.append(item)
            j += 1
        result[key] = items
        i = j if items else i + 1
    return result


def extract_display_name(text: str, fallback: str) -> str:
    body = FRONTMATTER_RE.sub("", text, count=1)
    m = H1_RE.search(body)
    if m:
        return m.group(1).strip()
    return fallback


def load_people(vault: Path) -> list[Person]:
    people_dir = vault / "rufino" / "_people"
    if not people_dir.is_dir():
        sys.stderr.write(f"[error] _people dir no existe: {people_dir}\n")
        sys.exit(2)
    people: list[Person] = []
    for f in sorted(people_dir.glob("*.md")):
        if f.name.startswith("_"):
            continue
        slug = f.stem
        text = f.read_text(encoding="utf-8")
        fm = parse_frontmatter(text)
        sources_val = fm.get("sources")
        sources = sources_val if isinstance(sources_val, list) else []
        display = extract_display_name(text, fallback=slug)
        people.append(Person(slug=slug, path=f, display_name=display, sources=sources))
    return people


# ─────────────────────────────────────────────────────────────────────────────
# Reference + shared-mention counting
# ─────────────────────────────────────────────────────────────────────────────

def iter_vault_md(vault: Path):
    """Itera todos los .md del vault salvo _archive/ y .obsidian/ y trash."""
    skip_parts = {"_archive", ".obsidian", ".trash", "node_modules"}
    for path in vault.rglob("*.md"):
        if any(part in skip_parts for part in path.parts):
            continue
        yield path


def count_references_and_shared(
    vault: Path, slugs: list[str]
) -> tuple[dict[str, int], dict[tuple[str, str], int]]:
    """Recorre el vault una sola vez.

    refs[slug] = cuántas notas (distintas del propio archivo) contienen
                 [[<slug>]] o `persona/<slug>` tag.
    shared[(a, b)] = cuántas notas mencionan AMBOS slugs (a < b lex).
    """
    refs: dict[str, int] = {s: 0 for s in slugs}
    shared: dict[tuple[str, str], int] = {}
    slug_set = set(slugs)
    for path in iter_vault_md(vault):
        rel = path.as_posix()
        # Detectar si esta nota ES un _people/<slug>.md.
        own_slug: str | None = None
        if "/rufino/_people/" in rel and rel.endswith(".md"):
            candidate = path.stem
            if candidate in slug_set:
                own_slug = candidate
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        found: set[str] = set()
        for slug in slug_set:
            # No contar self-references dentro del propio archivo de la persona.
            if own_slug == slug:
                continue
            wikilink_pat = r"\[\[(?:[^\[\]\|]*/)?" + re.escape(slug) + r"(?:\|[^\]]*)?\]\]"
            tag_pat = r"persona/" + re.escape(slug) + r"(?![\w-])"
            if re.search(wikilink_pat, text) or re.search(tag_pat, text):
                found.add(slug)
        for slug in found:
            refs[slug] += 1
        # Shared-mentions: si dos slugs aparecen en la misma nota, es señal de
        # que son personas distintas (Val los usó juntas). Pero las notas
        # dentro de _people/ son self-descripciones que suelen linkear al
        # "posible duplicado" — eso NO debe contar como shared.
        if own_slug is not None:
            continue
        if len(found) >= 2:
            for a, b in combinations(sorted(found), 2):
                shared[(a, b)] = shared.get((a, b), 0) + 1
    return refs, shared


# ─────────────────────────────────────────────────────────────────────────────
# Scoring
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Match:
    a: Person
    b: Person
    score: float
    band: str
    parts: dict[str, float]


def score_pair(a: Person, b: Person, shared_mentions: int) -> Match:
    name_a = normalize(a.display_name)
    name_b = normalize(b.display_name)
    n_lev = lev_ratio(name_a, name_b)
    n_jac = jaccard(tokens(a.display_name), tokens(b.display_name))
    s_sim = slug_similarity(a.slug, b.slug)
    subset = 1.0 if is_subset(a.display_name, b.display_name) else 0.0
    raw = (
        WEIGHTS["name_levenshtein"] * n_lev
        + WEIGHTS["name_jaccard"] * n_jac
        + WEIGHTS["slug_similarity"] * s_sim
        + WEIGHTS["subset_bonus"] * subset
    )
    # Penalización: si dos personas aparecen juntas en alguna nota, son distintas.
    if shared_mentions > 0:
        raw = 0.0
    band = "HIGH" if raw >= THRESHOLD_HIGH else ("MEDIUM" if raw >= THRESHOLD_MEDIUM else "LOW")
    return Match(
        a=a, b=b, score=round(raw, 4), band=band,
        parts={
            "name_levenshtein": round(n_lev, 4),
            "name_jaccard": round(n_jac, 4),
            "slug_similarity": round(s_sim, 4),
            "subset_bonus": subset,
            "shared_mentions": float(shared_mentions),
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# Question generation
# ─────────────────────────────────────────────────────────────────────────────

def question_filename(slug_a: str, slug_b: str) -> str:
    # Determinístico: orden lexicográfico para el filename.
    a, b = sorted([slug_a, slug_b])
    return f"person-resolution-{a}-vs-{b}.md"


def existing_question_paths(questions_dir: Path, slug_a: str, slug_b: str) -> list[Path]:
    """Idempotencia: revisar AMBOS órdenes (a-vs-b y b-vs-a) en raíz y _archive."""
    candidates: list[Path] = []
    a, b = slug_a, slug_b
    for first, second in [(a, b), (b, a)]:
        name = f"person-resolution-{first}-vs-{second}.md"
        candidates.append(questions_dir / name)
        candidates.append(questions_dir / "_archive" / name)
    return [p for p in candidates if p.exists()]


def render_question(match: Match, refs: dict[str, int]) -> str:
    a, b = match.a, match.b
    today = date.today().isoformat()
    # Filename ordena alfabéticamente, pero adentro mostramos A y B en el orden
    # del filename para que slug_a/slug_b coincida con lo que dice el id.
    if a.slug > b.slug:
        a, b = b, a
    sources_a = "[" + ", ".join(a.sources) + "]" if a.sources else "[]"
    sources_b = "[" + ", ".join(b.sources) + "]" if b.sources else "[]"
    sources_a_yaml = ("[" + ", ".join(a.sources) + "]") if a.sources else "[]"
    sources_b_yaml = ("[" + ", ".join(b.sources) + "]") if b.sources else "[]"
    qid = f"person-resolution-{a.slug}-vs-{b.slug}"
    title = f'¿{a.display_name} es la misma persona que {b.display_name}?'
    ref_a = refs.get(a.slug, 0)
    ref_b = refs.get(b.slug, 0)
    return (
        "---\n"
        f"id: {qid}\n"
        f'title: "{title}"\n'
        "type: person-resolution\n"
        "status: pending\n"
        f"created: {today}\n"
        f"created_by: {CREATED_BY}\n"
        "context:\n"
        "  refs:\n"
        f"    - {a.slug}\n"
        f"    - {b.slug}\n"
        "  data:\n"
        f"    slug_a: {a.slug}\n"
        f"    slug_b: {b.slug}\n"
        f"    score: {match.score}\n"
        f"    score_band: {match.band}\n"
        f"    sources_a: {sources_a_yaml}\n"
        f"    sources_b: {sources_b_yaml}\n"
        "priority: medium\n"
        "---\n"
        "\n"
        f"# {title}\n"
        "\n"
        f"El resolver detectó posible match. Score: {match.score} (banda {match.band}).\n"
        "\n"
        f"**A** (`_people/{a.slug}.md`): {a.display_name} — sources: {sources_a} — mencionado en {ref_a} notas.\n"
        f"**B** (`_people/{b.slug}.md`): {b.display_name} — sources: {sources_b} — mencionado en {ref_b} notas.\n"
        "\n"
        "## Opciones\n"
        "\n"
        f"- [ ] **Sí, son la misma persona** — mergear `{b.slug}` en `{a.slug}`. Re-puntear wikilinks de notas que apuntan a `{b.slug}`.\n"
        "- [ ] **No, son personas distintas** — agregar nota clarificadora en cada body.\n"
        "- [ ] **Otra (escribir abajo)**\n"
        "\n"
        "## Respuesta de Val\n"
        "\n"
        "_(esperando)_\n"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Cross-source person resolver")
    parser.add_argument("--dry-run", action="store_true",
                        help="No escribir archivos; solo reportar.")
    parser.add_argument("--threshold", type=float, default=THRESHOLD_MEDIUM,
                        help=f"Score mínimo para generar question (default {THRESHOLD_MEDIUM}).")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Imprime también los pares LOW.")
    args = parser.parse_args()

    vault_str = os.environ.get("RUFINO_VAULT_PATH")
    if not vault_str:
        sys.stderr.write("[error] RUFINO_VAULT_PATH no está seteado.\n")
        return 2
    vault = Path(vault_str).expanduser().resolve()
    if not vault.is_dir():
        sys.stderr.write(f"[error] vault no existe: {vault}\n")
        return 2

    questions_dir = vault / "questions"
    archive_dir = questions_dir / "_archive"

    people = load_people(vault)
    print(f"[info] {len(people)} personas cargadas desde {vault / 'rufino' / '_people'}")
    print(f"[info] {len(people) * (len(people) - 1) // 2} pares posibles")

    slugs = [p.slug for p in people]
    refs, shared = count_references_and_shared(vault, slugs)

    matches: list[Match] = []
    for a, b in combinations(people, 2):
        key = tuple(sorted([a.slug, b.slug]))
        sm = shared.get(key, 0)
        m = score_pair(a, b, sm)
        matches.append(m)

    matches.sort(key=lambda m: m.score, reverse=True)

    above_threshold = [m for m in matches if m.score >= args.threshold]
    print(f"[info] {len(above_threshold)} pares con score >= {args.threshold}")

    if args.verbose:
        print("\n[debug] todos los pares ordenados:")
        for m in matches[:30]:
            print(f"  {m.a.slug:25s} vs {m.b.slug:25s} → {m.score:.3f} ({m.band})  parts={m.parts}")

    created = 0
    skipped_existing = 0
    if not args.dry_run:
        questions_dir.mkdir(parents=True, exist_ok=True)

    for m in above_threshold:
        existing = existing_question_paths(questions_dir, m.a.slug, m.b.slug)
        if existing:
            skipped_existing += 1
            print(f"[skip] ya existe question para {m.a.slug} vs {m.b.slug}: "
                  f"{existing[0].relative_to(vault)}")
            continue
        target = questions_dir / question_filename(m.a.slug, m.b.slug)
        content = render_question(m, refs)
        if args.dry_run:
            print(f"[dry-run] would create {target.relative_to(vault)} "
                  f"(score={m.score}, band={m.band})")
        else:
            target.write_text(content, encoding="utf-8")
            print(f"[create] {target.relative_to(vault)} (score={m.score}, band={m.band})")
        created += 1

    print()
    print(f"[summary] threshold={args.threshold}")
    print(f"[summary] matches above threshold: {len(above_threshold)}")
    print(f"[summary] skipped (already existed): {skipped_existing}")
    print(f"[summary] {'would create' if args.dry_run else 'created'}: {created}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
