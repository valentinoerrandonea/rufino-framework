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
2. Leé el estado actual del vault: `_meta/_tags.md`, `_meta/_index.md` y
   `conceptos/`.
3. Detectá conceptos duplicados emitidos independientemente por workers
   distintos.
4. Producí UN solo archivo: `{run_dir}/consolidation-plan.json` con este
   schema (todos los keys son listas; pueden estar vacías):

{{
  "moves": [{{"from": "<relative-to-run-dir>", "to": "<relative-to-vault>"}}, ...],
  "concept_writes": [{{"path": "conceptos/<slug>.md", "content": "...", "wins_over": [...]}}, ...],
  "tag_index_updates": [{{"tag": "<tag>", "notes": ["<slug>", ...]}}, ...],
  "log_entries": ["<line>", ...]
}}

Tools allowed: Read, Glob, Write, mcp__ask-rufino-{slug}__*. Usá Write SOLO para
el plan path.
"""


@dataclass(frozen=True)
class ConsolidationPlan:
    moves: list[dict[str, str]] = field(default_factory=list)
    concept_writes: list[dict[str, Any]] = field(default_factory=list)
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
    for m in raw["moves"]:
        if not isinstance(m, dict) or "from" not in m or "to" not in m:
            raise ConsolidationError(f"bad move entry: {m!r}")
    for cw in raw["concept_writes"]:
        if not isinstance(cw, dict) or "path" not in cw or "content" not in cw:
            raise ConsolidationError(f"bad concept_write entry: {cw!r}")
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
