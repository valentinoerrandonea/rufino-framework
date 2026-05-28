"""Post-hoc validation of worker outputs against the adapter manifest."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

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

if TYPE_CHECKING:  # pragma: no cover — type-checker only
    from rufino.engine.process.batch.planner import WorkerAssignment


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
    *,
    assignment: "WorkerAssignment | None" = None,
) -> ValidationReport:
    """Validate worker output against the manifest.

    When ``assignment`` is provided, the validator is assignment-aware: every
    note in ``assignment.notes`` must produce exactly one terminal artifact —
    a valid augmented file (+ delta), a pending Q&A entry, or a synthesized
    failure. A worker that produced no output (empty/timeout/nonzero exit)
    is no longer silently dropped; each unaccounted note becomes a failure.

    Without an assignment, falls back to the legacy "enumerate augmented/"
    behavior for backward compatibility with callers that don't have an
    assignment in hand (e.g. retry helpers, ad-hoc tests).
    """
    aug_dir = staging_dir / "augmented"
    pending_dir = staging_dir / "pending"
    delta_dir = staging_dir / "deltas"
    passed: list[NoteValidation] = []
    failed: list[NoteValidation] = []

    if assignment is None:
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

    # Detect stem collisions within the assignment (nested paths can produce
    # two notes with the same stem). Without this, the second iteration's
    # file lookups would find the first one's artifacts and silently misreport.
    stems_seen: set[str] = set()
    for note_path in assignment.notes:
        slug = note_path.stem
        if slug in stems_seen:
            failed.append(NoteValidation(
                slug=slug,
                augmented_path=aug_dir / f"{slug}.md",
                delta_path=None,
                errors=(
                    f"slug collision within assignment for slug={slug!r}; "
                    "stager should have caught this",
                ),
            ))
            continue
        stems_seen.add(slug)

        aug_path = aug_dir / f"{slug}.md"
        delta_path = delta_dir / f"{slug}.json"
        pending_path = pending_dir / f"{slug}.json"
        aug_exists = aug_path.exists()
        pending_exists = pending_path.exists()

        if aug_exists and pending_exists:
            # Malformed worker output: a note cannot be both finalized and
            # pending. Surface as failure rather than letting precedence
            # silently pick one.
            failed.append(NoteValidation(
                slug=slug,
                augmented_path=aug_path,
                delta_path=delta_path if delta_path.exists() else None,
                errors=(
                    f"worker produced both augmented and pending for slug={slug!r}",
                ),
            ))
        elif aug_exists:
            result = validate_one(aug_path, delta_path, manifest)
            (passed if result.passed else failed).append(result)
        elif pending_exists:
            # Pending Q&A is a valid non-failure terminal state; do not list.
            continue
        else:
            failed.append(NoteValidation(
                slug=slug,
                augmented_path=aug_path,
                delta_path=None,
                errors=(f"worker produced no output for slug={slug!r}",),
            ))
    return ValidationReport(passed=tuple(passed), failed=tuple(failed))


@dataclass(frozen=True)
class CompressionCheck:
    ratio: float
    below_floor: bool


def check_compression_ratio(
    *,
    original: Path,
    augmented: Path,
    floor: float | None,
) -> CompressionCheck | None:
    if floor is None:
        return None
    # PDFs have no faithful word-count denominator (binary format).
    if original.suffix.lower() == ".pdf":
        return None
    orig_words = _count_body_words(original)
    aug_words = _count_body_words(augmented)
    if orig_words == 0:
        return CompressionCheck(ratio=1.0, below_floor=False)
    ratio = aug_words / orig_words
    below = ratio < floor
    if below:
        log.warning(
            "compression below floor: %s ratio=%.2f floor=%.2f "
            "(orig=%d words, aug=%d words)",
            augmented.name, ratio, floor, orig_words, aug_words,
        )
    return CompressionCheck(ratio=ratio, below_floor=below)


def _count_body_words(path: Path) -> int:
    text = path.read_text(encoding="utf-8", errors="replace")
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            text = text[end + 5:]
    return len(text.split())
