"""Construct the system prompt handed to each Claude worker subprocess.

Three concatenated blocks (preamble + adapter prompt + vault context),
exactly as described in spec §2.4.
"""
from pathlib import Path

from rufino.engine.process.batch.planner import WorkerAssignment
from rufino.engine.process.manifest import WorkerAdapterManifest


_PREAMBLE_TEMPLATE = """\
Sos un worker de Rufino procesando notas en batch.

Tu asignación (worker_id={worker_id}, grupo={group}):

{note_lines}

Staging dir (escribí AQUÍ y nada más fuera de acá): {staging_dir}
{compression_block}
Para CADA nota tenés que producir dos archivos en el staging dir:

  - `augmented/<slug>.md` — la nota augmentada con frontmatter YAML cumpliendo
    el output_schema del adapter, body en markdown, triples en el vocabulario
    permitido, tags en los ejes declarados.
  - `deltas/<slug>.json` — un JSON con los cambios:
    {{
      "note_slug": "<slug>",
      "tags_added": [...],
      "triples_emitted": [{{"s":"...","r":"...","o":"..."}}, ...],
      "concepts_referenced": [...],
      "concepts_promoted": [...],
      "wikilinks_added": [...],
      "qa_opened": [],
      "warnings": []
    }}

Si la nota dispara un Q&A trigger del adapter, NO escribas augmented/<slug>.md
ni deltas/<slug>.json para esa nota. Escribí en su lugar:

  - `pending/<slug>.json` con este formato:
    {{
      "origin": "process-batch",
      "run_id": "{run_id}",
      "worker_id": "{worker_id}",
      "pending_note": "<slug>",
      "input_path": "<input-path-relative-to-vault>",
      "trigger": "<qa_trigger-name>",
      "context": "<resumen para retomar tras la respuesta>",
      "question": "<la pregunta concreta al usuario>"
    }}

ASK-USER marker (usalo SOLO cuando un qa_trigger del adapter aplique).

Vocabulario permitido de triples (cualquier otro lo rechazo y te hago retry):
{vocab_block}

Required fields del output_schema (todos deben aparecer en el frontmatter):
{required_block}

Q&A triggers declarados por el adapter (si alguno aplica, NO augmentes — emití pending/<slug>.json):
{qa_triggers_block}

Tipos de errores típicos a evitar:
  - triples con relaciones fuera del vocabulario (te las rechazo y te hago retry)
  - frontmatter sin los required fields del output_schema
  - destination_path con caracteres ilegales / escapes a otro vault

Cuando termines, no contestes nada al stdout — todo el resultado son archivos
en el staging.
"""

_VAULT_CONTEXT_TEMPLATE = """\

Tenés acceso al MCP `ask-rufino-{slug}`. Usalo para:
  - buscar conceptos ya promovidos en el vault (evitá duplicarlos)
  - detectar wikilinks naturales (notas relacionadas)
  - resolver contextos ambiguos antes de inventar
{concepts_block}
"""


def _format_qa_triggers(
    qa_triggers: tuple[object, ...],
) -> str:
    """Format the manifest's ``qa_triggers`` as a bullet list of name+condition.

    Each trigger is rendered as ``  - <name>: <condition>``. Missing fields
    degrade gracefully (``(sin nombre)`` / ``(sin condición)``) so a malformed
    manifest still produces a usable prompt — the worker prompt is not where
    we want to crash. Empty list renders as ``(ninguno)``.
    """
    if not qa_triggers:
        return "  (ninguno)"
    lines: list[str] = []
    for trig in qa_triggers:
        # qa_triggers are MappingProxyType after _freeze, but we use .get
        # via getattr to also tolerate plain dicts (tests + future shapes).
        getter = getattr(trig, "get", None)
        if getter is None:
            lines.append(f"  - {trig!r}")
            continue
        name = getter("name") or "(sin nombre)"
        condition = getter("condition") or "(sin condición)"
        lines.append(f"  - {name}: {condition}")
    return "\n".join(lines)


def build_worker_system_prompt(
    *,
    manifest: WorkerAdapterManifest,
    adapter_prompt_text: str,
    assignment: WorkerAssignment,
    vault_slug: str,
    staging_dir: Path,
    vault_concepts_top_n: list[str],
    run_id: str,
) -> str:
    note_lines = "\n".join(f"  - {p}" for p in assignment.notes)
    vocab_block = "\n".join(f"  - {r}" for r in manifest.triple_vocabulary) or "  (ninguno)"
    required_fields = manifest.output_schema.get("required", {})
    if required_fields:
        required_block = "\n".join(
            f"  - {name}: {ftype}" for name, ftype in required_fields.items()
        )
    else:
        required_block = "  (ninguno)"
    qa_triggers_block = _format_qa_triggers(manifest.qa_triggers)
    if manifest.compression_floor is not None:
        floor_pct = int(round(manifest.compression_floor * 100))
        compression_block = (
            f"\nFidelity floor: el body reescrito debe conservar al menos el "
            f"{floor_pct}% del volumen original (palabras del input vs palabras "
            f"del output). Reescribir para claridad NO significa resumir. "
            f"Si tenés que elegir entre acortar o ser fiel, sé fiel.\n"
        )
    else:
        compression_block = ""
    preamble = _PREAMBLE_TEMPLATE.format(
        worker_id=assignment.worker_id,
        group=assignment.group,
        note_lines=note_lines,
        staging_dir=staging_dir,
        run_id=run_id,
        vocab_block=vocab_block,
        required_block=required_block,
        qa_triggers_block=qa_triggers_block,
        compression_block=compression_block,
    )
    concepts_block = ""
    if vault_concepts_top_n:
        bullets = "\n".join(f"  - {c}" for c in vault_concepts_top_n)
        concepts_block = (
            "\nConceptos ya presentes en el vault (preferí reusar):\n"
            f"{bullets}\n"
        )
    vault_context = _VAULT_CONTEXT_TEMPLATE.format(
        slug=vault_slug, concepts_block=concepts_block,
    )
    return f"{preamble}\n---\n{adapter_prompt_text}\n---\n{vault_context}"


_RETRY_TEMPLATE = """

RETRY

Procesaste esta nota antes y el output no pasó validación. Errores específicos:

{error_lines}

El input original sigue siendo el mismo. Rehacelo corrigiendo SOLO los puntos
listados; el resto del trabajo está OK y no hace falta retocar.
"""


def build_retry_appendix(errors: list[str]) -> str:
    lines = "\n".join(f"  - {e}" for e in errors)
    return _RETRY_TEMPLATE.format(error_lines=lines)
