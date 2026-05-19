"""Post-hoc validation of worker outputs against the adapter manifest."""
import json
from dataclasses import dataclass, field
from pathlib import Path

from rufino.engine.process.helpers.frontmatter import (
    parse_frontmatter,
    validate_against_schema,
)
from rufino.engine.process.helpers.triples import (
    extract_triples,
    validate_triples_against_vocab,
)
from rufino.engine.process.manifest import WorkerAdapterManifest


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


def _validate_one(
    augmented_path: Path,
    delta_path: Path,
    manifest: WorkerAdapterManifest,
) -> NoteValidation:
    errors: list[str] = []
    slug = augmented_path.stem

    try:
        text = augmented_path.read_text(encoding="utf-8")
        fm, _body = parse_frontmatter(text)
    except Exception as e:
        return NoteValidation(
            slug=slug, augmented_path=augmented_path, delta_path=None,
            errors=(f"failed to parse frontmatter: {e}",),
        )

    try:
        validate_against_schema(fm, manifest.output_schema)
    except Exception as e:
        errors.append(f"schema violation: {e}")

    try:
        triples = extract_triples(fm)
        validate_triples_against_vocab(triples, set(manifest.triple_vocabulary))
    except Exception as e:
        errors.append(f"triple validation: {e}")

    if not delta_path.exists():
        errors.append("delta json file missing")
    else:
        try:
            json.loads(delta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            errors.append(f"delta json parse error: {e}")

    return NoteValidation(
        slug=slug, augmented_path=augmented_path,
        delta_path=delta_path if delta_path.exists() else None,
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
        return ValidationReport()
    for aug_path in sorted(aug_dir.glob("*.md")):
        delta_path = delta_dir / f"{aug_path.stem}.json"
        result = _validate_one(aug_path, delta_path, manifest)
        (passed if result.passed else failed).append(result)
    return ValidationReport(passed=tuple(passed), failed=tuple(failed))
