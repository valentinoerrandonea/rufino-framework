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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rufino.engine.process.batch.errors import ConsolidationError
from rufino.engine.process.batch.runner_helper import MAX_OUTPUT_BYTES, run_claude


log = logging.getLogger(__name__)


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


@dataclass(frozen=True)
class ConsolidationPlan:
    moves: list[dict[str, str]] = field(default_factory=list)
    concept_writes: list[dict[str, Any]] = field(default_factory=list)
    author_writes: list[dict[str, Any]] = field(default_factory=list)
    tag_index_updates: list[dict[str, Any]] = field(default_factory=list)
    log_entries: list[str] = field(default_factory=list)


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
    for m in raw["moves"]:
        if not isinstance(m, dict) or "from" not in m or "to" not in m:
            raise ConsolidationError(f"bad move entry: {m!r}")
    for cw in raw["concept_writes"]:
        if not isinstance(cw, dict) or "path" not in cw or "content" not in cw:
            raise ConsolidationError(f"bad concept_write entry: {cw!r}")
    for aw in author_writes_raw:
        if not isinstance(aw, dict) or "path" not in aw or "content" not in aw:
            raise ConsolidationError(f"bad author_write entry: {aw!r}")
    for tu in raw["tag_index_updates"]:
        if (
            not isinstance(tu, dict)
            or "tag" not in tu
            or not isinstance(tu.get("notes"), list)
        ):
            raise ConsolidationError(f"bad tag_index_update entry: {tu!r}")
    return ConsolidationPlan(
        moves=list(raw["moves"]),
        concept_writes=list(raw["concept_writes"]),
        author_writes=list(author_writes_raw),
        tag_index_updates=list(raw["tag_index_updates"]),
        log_entries=list(raw["log_entries"]),
    )


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
