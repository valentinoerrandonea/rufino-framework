from dataclasses import dataclass
from pathlib import Path
from rufino.engine.process.manifest import parse_worker_manifest
from rufino.engine.process.helpers.frontmatter import (
    parse_frontmatter,
    render_frontmatter,
    validate_against_schema,
)
from rufino.engine.process.helpers.triples import (
    extract_triples,
    validate_triples_against_vocab,
)
from rufino.engine.process.helpers.indices import update_tag_index, append_to_log
from rufino.engine.process.context_injectors import apply_context_injectors


@dataclass
class ProcessResult:
    success: bool
    note_path: Path
    message: str = ""


def process_note(
    *,
    note_path: Path,
    vault_root: Path,
    mode: str,
    adapter_dir: Path | None = None,
    llm_client=None,
    query_layer=None,
    qa_loop=None,
) -> ProcessResult:
    """Process a note. Modes: light (indices only), full (LLM augment), lint (validate)."""
    if mode == "light":
        return _process_light(note_path=note_path, vault_root=vault_root)
    if mode == "full":
        if adapter_dir is None or llm_client is None or query_layer is None or qa_loop is None:
            raise ValueError("full mode requires adapter_dir, llm_client, query_layer, qa_loop")
        return _process_full(
            note_path=note_path,
            vault_root=vault_root,
            adapter_dir=adapter_dir,
            llm_client=llm_client,
            query_layer=query_layer,
            qa_loop=qa_loop,
        )
    raise NotImplementedError(f"Mode {mode!r} not implemented")


def _process_light(*, note_path: Path, vault_root: Path) -> ProcessResult:
    text = note_path.read_text()
    fm, _body = parse_frontmatter(text)
    tags = fm.get("tags", [])

    tag_index = vault_root / "_meta" / "_tags.md"
    note_slug = note_path.stem
    for tag in tags:
        update_tag_index(tag_index, tag=tag, note_slug=note_slug)

    log = vault_root / "_meta" / "_processing-log.md"
    append_to_log(log, message=f"light-processed {note_slug}")

    return ProcessResult(success=True, note_path=note_path, message="light OK")


def _process_full(
    *,
    note_path: Path,
    vault_root: Path,
    adapter_dir: Path,
    llm_client,
    query_layer,
    qa_loop,
) -> ProcessResult:
    manifest = parse_worker_manifest((adapter_dir / "manifest.yaml").read_text())
    prompt_template = (adapter_dir / "prompt.md").read_text()

    raw = note_path.read_text()
    current_fm, current_body = parse_frontmatter(raw)
    variables = {k: v for k, v in current_fm.items() if isinstance(v, str)}

    context = apply_context_injectors(
        injectors=list(manifest.context_injectors),
        variables=variables,
        query=query_layer,
    )

    rendered = prompt_template.replace("{{note_body}}", current_body)
    for key, val in context.items():
        rendered = rendered.replace(f"{{{{context.{key}}}}}", val)

    llm_response = llm_client.complete(prompt=rendered, model=manifest.llm)

    augmented_fm, augmented_body = parse_frontmatter(llm_response.text)

    validate_against_schema(augmented_fm, manifest.output_schema)
    triples = extract_triples(augmented_fm)
    validate_triples_against_vocab(triples, set(manifest.triple_vocabulary))

    note_slug = note_path.stem
    dest_rel = manifest.destination_path.format(
        slug=note_slug,
        **{k: v for k, v in augmented_fm.items() if isinstance(v, str)},
    )
    dest = vault_root / dest_rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(render_frontmatter(augmented_fm, augmented_body))
    note_path.unlink()

    tag_index = vault_root / "_meta" / "_tags.md"
    for tag in augmented_fm.get("tags", []):
        update_tag_index(tag_index, tag=tag, note_slug=note_slug)
    append_to_log(
        vault_root / "_meta" / "_processing-log.md",
        message=f"full-processed {note_slug} → {dest_rel}",
    )

    return ProcessResult(success=True, note_path=dest, message=f"moved to {dest_rel}")
