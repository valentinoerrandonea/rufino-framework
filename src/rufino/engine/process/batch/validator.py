"""Post-hoc validation of worker outputs against the adapter manifest."""
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from rufino.engine.process.helpers.frontmatter import (
    FrontmatterError,
    parse_frontmatter,
    validate_against_schema,
)
from rufino.engine.process.helpers.triples import (
    TripleError,
    extract_triples,
    validate_triples_against_vocab,
)
from rufino.engine.process.manifest import WorkerAdapterManifest


log = logging.getLogger(__name__)


@dataclass(frozen=True)
class NoteValidation:
    slug: str
    augmented_path: Path
    delta_path: Path | None
    errors: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class ValidationReport:
    passed: tuple[NoteValidation, ...] = field(default_factory=tuple)
    failed: tuple[NoteValidation, ...] = field(default_factory=tuple)


def validate_one(
    augmented_path: Path,
    delta_path: Path,
    manifest: WorkerAdapterManifest,
) -> NoteValidation:
    errors: list[str] = []
    slug = augmented_path.stem

    try:
        text = augmented_path.read_text(encoding="utf-8")
    except OSError as e:
        return NoteValidation(
            slug=slug, augmented_path=augmented_path, delta_path=None,
            errors=(f"cannot read augmented file: {e}",),
        )
    except UnicodeDecodeError as e:
        return NoteValidation(
            slug=slug, augmented_path=augmented_path, delta_path=None,
            errors=(f"augmented file is not valid utf-8: {e}",),
        )

    try:
        fm, _body = parse_frontmatter(text)
    except FrontmatterError as e:
        return NoteValidation(
            slug=slug, augmented_path=augmented_path, delta_path=None,
            errors=(f"failed to parse frontmatter: {e}",),
        )

    try:
        validate_against_schema(fm, manifest.output_schema)
    except FrontmatterError as e:
        errors.append(f"schema violation: {e}")

    try:
        triples = extract_triples(fm)
        validate_triples_against_vocab(triples, set(manifest.triple_vocabulary))
    except TripleError as e:
        errors.append(f"triple validation: {e}")

    delta_exists = delta_path.exists()
    if not delta_exists:
        errors.append("delta json file missing")
    else:
        try:
            json.loads(delta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            errors.append(f"delta json parse error: {e}")

    return NoteValidation(
        slug=slug, augmented_path=augmented_path,
        delta_path=delta_path if delta_exists else None,
        errors=tuple(errors),
    )


def validate_worker_output(
    staging_dir: Path,
    manifest: WorkerAdapterManifest,
) -> ValidationReport:
    aug_dir = staging_dir / "augmented"
    delta_dir = staging_dir / "deltas"
    passed: list[NoteValidation] = []
    failed: list[NoteValidation] = []
    if not aug_dir.exists():
        log.info(
            "no augmented/ in %s; treating as pending-only or empty worker output",
            staging_dir,
        )
        return ValidationReport()
    for aug_path in sorted(aug_dir.glob("*.md")):
        delta_path = delta_dir / f"{aug_path.stem}.json"
        result = validate_one(aug_path, delta_path, manifest)
        (passed if result.passed else failed).append(result)
    return ValidationReport(passed=tuple(passed), failed=tuple(failed))
