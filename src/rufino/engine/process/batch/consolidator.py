"""Run the consolidator: one `claude` invocation reads all workers' outputs
and emits `consolidation-plan.json` that Rufino then commits via the
transaction log.

If the consolidator times out or returns an empty plan, callers should
fall back to a naive commit (each augmented.md → destination, indices
appended per-delta, no cross-grupo concept dedup).
"""
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rufino.engine.process.batch.errors import ConsolidationError
from rufino.engine.process.batch.runner_helper import MAX_OUTPUT_BYTES, run_claude


log = logging.getLogger(__name__)


def _reject_dot_segments(path: str, *, where: str) -> None:
    """A path with `.` or `..` segments resolves to a different on-disk
    location than its string form suggests, which breaks string-keyed dedupe.
    Reject at construction so the invariant lives where the type is defined."""
    parts = path.split("/")
    if any(p in (".", "..") for p in parts):
        raise ValueError(
            f"{where} must not contain '.' or '..' segments, got {path!r}"
        )


@dataclass(frozen=True)
class Move:
    from_: str
    to: str

    def __post_init__(self) -> None:
        if not isinstance(self.from_, str) or not self.from_:
            raise ValueError("move.from must be a non-empty string")
        if not isinstance(self.to, str) or not self.to:
            raise ValueError("move.to must be a non-empty string")
        if self.from_ == self.to:
            raise ValueError(
                f"move.from and move.to are identical: {self.to!r}"
            )


@dataclass(frozen=True)
class ConceptWrite:
    path: str
    content: str
    wins_over: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.path, str) or not self.path:
            raise ValueError("concept_write.path must be a non-empty string")
        if not self.path.startswith("conceptos/") or not self.path.endswith(".md"):
            raise ValueError(
                f"concept_write.path must be under conceptos/ and end in .md, "
                f"got {self.path!r}"
            )
        _reject_dot_segments(self.path, where="concept_write.path")
        if not isinstance(self.content, str) or not self.content.strip():
            raise ValueError("concept_write.content must be a non-empty string")


@dataclass(frozen=True)
class AuthorWrite:
    path: str
    content: str
    wins_over: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.path, str) or not self.path:
            raise ValueError("author_write.path must be a non-empty string")
        if not self.path.startswith("autores/") or not self.path.endswith(".md"):
            raise ValueError(
                f"author_write.path must be under autores/ and end in .md, "
                f"got {self.path!r}"
            )
        _reject_dot_segments(self.path, where="author_write.path")
        if not isinstance(self.content, str) or not self.content.strip():
            raise ValueError("author_write.content must be a non-empty string")


@dataclass(frozen=True)
class TagIndexUpdate:
    tag: str
    notes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.tag, str) or not self.tag:
            raise ValueError("tag_index_update.tag must be a non-empty string")
        if not all(isinstance(n, str) and n for n in self.notes):
            raise ValueError("tag_index_update.notes must be a tuple of non-empty strings")


_CONSOLIDATOR_PREAMBLE = """\
Sos el consolidator de Rufino corriendo después de un batch de workers.

Tu trabajo:

1. Leé TODOS los archivos en `{run_dir}/workers/*/augmented/*.md` y
   `{run_dir}/workers/*/deltas/*.json`.
2. Leé el estado actual del vault: `_meta/_tags.md`, `_meta/_index.md`,
   `conceptos/` y `autores/`.
3. Detectá conceptos y autores duplicados emitidos independientemente por
   workers distintos.
4. Producí UN solo archivo: `{run_dir}/consolidation-plan.json` con este
   schema (todos los keys son listas; pueden estar vacías):

{{
  "moves": [{{"from": "<relative-to-run-dir>", "to": "<relative-to-vault>"}}, ...],
  "concept_writes": [{{"path": "conceptos/<slug>.md", "content": "...", "wins_over": [...]}}, ...],
  "author_writes": [{{"path": "autores/<slug>.md", "content": "...", "wins_over": [...]}}, ...],
  "tag_index_updates": [{{"tag": "<tag>", "notes": ["<slug>", ...]}}, ...],
  "log_entries": ["<line>", ...]
}}

Conceptos — body enriquecido (REQUERIDO):
  Para cada concepto promovido (que aparece en ≥ 2 deltas con
  `concepts_promoted`), leé los augmented.md donde aparece y sintetizá el
  cuerpo de la nota con esta estructura:

  ```
  ---
  tipo: concepto
  materias: [<lista de materias donde aparece>]
  formulado_por: [[<slug-autor>]]
  tags: [tipo/concepto, materia/<materia-principal>]
  ---
  # <Nombre del Concepto>

  **Definición:** <1 frase precisa, derivada de los apuntes>
  **Contexto:** <cuándo se aplica, qué problema resuelve>
  **Ejemplo:** <si los apuntes lo dan, transcribilo>
  **Relacionado con:** [[<concepto-vecino-1>]], [[<concepto-vecino-2>]]
  **Formulado por:** [[<autor>]]

  ## Apariciones
  - [[<apunte-1>]]
  - [[<apunte-2>]]
  ```

  Reglas duras:
  - Solo agregá `formulado_por` en el frontmatter si la atribución es
    unánime en los apuntes. Si es ambigua, omití la línea entera (tanto en
    frontmatter como la sección "**Formulado por:**" del cuerpo).
  - Si una sección no tiene material en los apuntes (ej. no aparece
    Ejemplo), OMITÍ esa línea entera. Mejor un hueco honesto que texto
    inventado. NO escribas placeholders tipo "_Expandi con tu propia
    explicacion_" ni "TODO: completar".
  - "**Relacionado con:**" tiene que apuntar a conceptos que aparezcan en
    el mismo apunte o en otro apunte de la misma materia — no inventes
    wikilinks sueltos.

Autores — body con bio + obra + relevancia (REQUERIDO):
  Para cada autor mencionado en ≥ 2 triples `referencia_autor` (al menos 2
  apuntes distintos), escribí una nota `autores/<slug>.md` con esta
  estructura:

  ```
  ---
  tipo: persona
  tags: [tipo/persona, persona/<slug>]
  ---
  # <Nombre completo del autor>

  **Bio:** <1 párrafo: quién es, cuándo, qué disciplina>
  **Obra principal:** <libro o paper canónico + año>
  **Por qué importa:** <aporte específico para las materias del vault>

  ## Conceptos asociados
  - [[<concepto-1>]]
  - [[<concepto-2>]]

  ## Apariciones
  - [[<apunte-1>]]
  ```

  Reglas duras:
  - Threshold mínimo: al menos 2 apariciones en triples `referencia_autor`.
    Si el autor aparece solo 1 vez o como mención lateral sin triple
    unánime, NO emitas el author_write — dejá la mención como wikilink
    roto, mejor un hueco honesto que una atribución inventada.
  - Mismas reglas anti-placeholder que conceptos: si no tenés material
    para una sección, omitíla, no la rellenes.

5. Tools allowed: Read, Glob, Write, mcp__ask-rufino-{slug}__*. Usá Write
   SOLO para el plan path.
"""


_MOVE_KEYS = frozenset({"from", "to"})
_CW_KEYS = frozenset({"path", "content", "wins_over"})
_AW_KEYS = frozenset({"path", "content", "wins_over"})
_TU_KEYS = frozenset({"tag", "notes"})


def _reject_extra_keys(value: dict, allowed: frozenset[str], *, where: str) -> None:
    extra = set(value) - allowed
    if extra:
        raise ValueError(
            f"{where} has unknown keys {sorted(extra)}: {value!r} "
            f"(typo or new field — strict by design)"
        )


def _to_move(value: Any) -> Move:
    if isinstance(value, Move):
        return value
    if not isinstance(value, dict) or "from" not in value or "to" not in value:
        raise ValueError(f"bad move entry: {value!r}")
    _reject_extra_keys(value, _MOVE_KEYS, where="move")
    return Move(from_=value["from"], to=value["to"])


def _to_concept_write(value: Any) -> ConceptWrite:
    if isinstance(value, ConceptWrite):
        return value
    if not isinstance(value, dict) or "path" not in value or "content" not in value:
        raise ValueError(f"bad concept_write entry: {value!r}")
    _reject_extra_keys(value, _CW_KEYS, where="concept_write")
    return ConceptWrite(
        path=value["path"],
        content=value["content"],
        wins_over=tuple(value.get("wins_over", ()) or ()),
    )


def _to_author_write(value: Any) -> AuthorWrite:
    if isinstance(value, AuthorWrite):
        return value
    if not isinstance(value, dict) or "path" not in value or "content" not in value:
        raise ValueError(f"bad author_write entry: {value!r}")
    _reject_extra_keys(value, _AW_KEYS, where="author_write")
    return AuthorWrite(
        path=value["path"],
        content=value["content"],
        wins_over=tuple(value.get("wins_over", ()) or ()),
    )


def _to_tag_index_update(value: Any) -> TagIndexUpdate:
    if isinstance(value, TagIndexUpdate):
        return value
    if (
        not isinstance(value, dict)
        or "tag" not in value
        or not isinstance(value.get("notes"), list)
    ):
        raise ValueError(f"bad tag_index_update entry: {value!r}")
    _reject_extra_keys(value, _TU_KEYS, where="tag_index_update")
    return TagIndexUpdate(tag=value["tag"], notes=tuple(value["notes"]))


@dataclass(frozen=True)
class ConsolidationPlan:
    moves: tuple[Move, ...] = ()
    concept_writes: tuple[ConceptWrite, ...] = ()
    author_writes: tuple[AuthorWrite, ...] = ()
    tag_index_updates: tuple[TagIndexUpdate, ...] = ()
    log_entries: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "moves", tuple(_to_move(m) for m in self.moves))
        object.__setattr__(self, "concept_writes", tuple(
            _to_concept_write(cw) for cw in self.concept_writes
        ))
        object.__setattr__(self, "author_writes", tuple(
            _to_author_write(aw) for aw in self.author_writes
        ))
        object.__setattr__(self, "tag_index_updates", tuple(
            _to_tag_index_update(tu) for tu in self.tag_index_updates
        ))
        object.__setattr__(self, "log_entries", tuple(self.log_entries))


def build_consolidator_system_prompt(*, run_dir: Path, vault_slug: str) -> str:
    return _CONSOLIDATOR_PREAMBLE.format(run_dir=run_dir, slug=vault_slug)


def validate_consolidation_plan(raw: dict[str, Any]) -> ConsolidationPlan:
    required_keys = {"moves", "concept_writes", "tag_index_updates", "log_entries"}
    missing = required_keys - set(raw.keys())
    if missing:
        raise ConsolidationError(f"consolidation plan missing keys: {sorted(missing)}")
    for k in required_keys:
        if not isinstance(raw[k], list):
            raise ConsolidationError(f"field {k!r} must be a list")
    author_writes_raw = raw.get("author_writes", [])
    if not isinstance(author_writes_raw, list):
        raise ConsolidationError("field 'author_writes' must be a list")
    try:
        return ConsolidationPlan(
            moves=tuple(_to_move(m) for m in raw["moves"]),
            concept_writes=tuple(_to_concept_write(cw) for cw in raw["concept_writes"]),
            author_writes=tuple(_to_author_write(aw) for aw in author_writes_raw),
            tag_index_updates=tuple(
                _to_tag_index_update(tu) for tu in raw["tag_index_updates"]
            ),
            log_entries=tuple(raw["log_entries"]),
        )
    except (TypeError, ValueError) as e:
        raise ConsolidationError(f"invalid consolidation plan: {e}") from e


async def run_consolidator(
    *,
    run_dir: Path,
    vault_slug: str,
    timeout_seconds: float = 600.0,
) -> ConsolidationPlan | None:
    """Invoke the consolidator subprocess. Returns parsed plan on success or
    None on timeout / empty-output (caller falls back to naive commit).
    """
    prompt = build_consolidator_system_prompt(run_dir=run_dir, vault_slug=vault_slug)
    plan_path = run_dir / "consolidation-plan.json"
    argv = [
        "claude", "-p",
        "--system-prompt", prompt,
        "--allowedTools", f"Read,Glob,Write,mcp__ask-rufino-{vault_slug}__*",
        "--",
        f"Escribí el plan a {plan_path}",
    ]
    env = os.environ.copy()
    result = await run_claude(
        argv=argv, cwd=run_dir, env=env, timeout_seconds=timeout_seconds,
    )
    if result.truncated:
        log.warning(
            "consolidator worker output truncated (cap=%d bytes). "
            "consolidation-plan.json may be incomplete.",
            MAX_OUTPUT_BYTES,
        )
    if result.exit_code == 124:  # timeout
        return None
    if not plan_path.exists():
        return None
    try:
        raw = json.loads(plan_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ConsolidationError(f"consolidation plan invalid JSON: {e}") from e
    return validate_consolidation_plan(raw)
