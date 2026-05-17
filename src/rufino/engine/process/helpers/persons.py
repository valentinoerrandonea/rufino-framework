from pathlib import Path


def register_persons(people_dir: Path, *, persons: list[str]) -> list[str]:
    """For each person slug not yet in `people_dir`, create a stub note.

    Returns list of newly created slugs.
    """
    created: list[str] = []
    for slug in persons:
        target = people_dir / f"{slug}.md"
        if target.exists():
            continue
        target.write_text(
            f"---\ntags: [tipo/persona, persona/{slug}]\n---\n"
            f"# {slug}\n\n(stub — completar con contexto)\n"
        )
        created.append(slug)
    return created
