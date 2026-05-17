from pathlib import Path


def promote_concepts(
    conceptos_dir: Path,
    *,
    mentions: dict[str, int],
    threshold: int,
) -> list[str]:
    """For each concept slug with mentions >= threshold, create a stub note if absent.

    Returns list of newly promoted concept slugs.
    """
    promoted: list[str] = []
    for slug, count in mentions.items():
        if count < threshold:
            continue
        target = conceptos_dir / f"{slug}.md"
        if target.exists():
            continue
        target.write_text(
            f"---\ntags: [tipo/concepto, concepto/{slug}]\n---\n"
            f"# {slug}\n\nConcepto promovido automáticamente ({count} menciones).\n"
        )
        promoted.append(slug)
    return promoted
