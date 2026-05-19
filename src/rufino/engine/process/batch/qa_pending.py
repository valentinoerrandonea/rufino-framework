"""Collect pending Q&A blocks emitted by workers and write them to the vault.

Workers can decide a note triggers a qa_trigger from the adapter; in that case
they write `pending/<slug>.json` in their staging dir instead of the usual
augmented/+deltas/ pair. Rufino, after VALIDATE, scans for these and writes
a Q&A note into the vault's `questions/` directory.
"""
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from rufino.engine.process.batch.errors import BatchError
from rufino.engine.process.helpers.frontmatter import FrontmatterError, parse_frontmatter


log = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"^[A-Za-z0-9._-]+$")


class InvalidPendingSlugError(BatchError):
    """Raised when a worker's pending_note slug would escape questions/."""


@dataclass(frozen=True)
class PendingQA:
    origin: str
    run_id: str
    worker_id: str
    pending_note: str
    input_path: str
    trigger: str
    context: str
    question: str


@dataclass(frozen=True)
class WriteResult:
    written: tuple[Path, ...] = field(default_factory=tuple)
    skipped: tuple[Path, ...] = field(default_factory=tuple)
    failed: tuple[Path, ...] = field(default_factory=tuple)


def _validate_slug(value: str, field_name: str) -> None:
    if not _SLUG_RE.fullmatch(value):
        raise InvalidPendingSlugError(
            f"{field_name}={value!r} contains characters outside [A-Za-z0-9._-]"
        )


def collect_pending(run_dir: Path) -> list[PendingQA]:
    out: list[PendingQA] = []
    workers_root = run_dir / "workers"
    if not workers_root.exists():
        return out
    for worker_dir in sorted(workers_root.iterdir()):
        pending_dir = worker_dir / "pending"
        if not pending_dir.is_dir():
            continue
        for p in sorted(pending_dir.glob("*.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                log.warning("dropping malformed pending json at %s: %s", p, e)
                continue
            if not isinstance(data, dict):
                log.warning("dropping %s: payload must be a JSON object", p)
                continue
            # All string fields must actually be strings — a non-string slug
            # would escape _validate_slug as a TypeError, and a non-string
            # trigger/context/question would render garbage into the
            # question file body.
            _required_strs = (
                "origin", "run_id", "worker_id", "pending_note",
                "input_path", "trigger", "question",
            )
            bad = next(
                (k for k in _required_strs if not isinstance(data.get(k), str)),
                None,
            )
            if bad is not None:
                log.warning("dropping %s: %s must be a string", p, bad)
                continue
            if "context" in data and not isinstance(data["context"], str):
                log.warning("dropping %s: context must be a string", p)
                continue
            try:
                out.append(PendingQA(
                    origin=data["origin"], run_id=data["run_id"],
                    worker_id=data["worker_id"], pending_note=data["pending_note"],
                    input_path=data["input_path"], trigger=data["trigger"],
                    context=data.get("context", ""), question=data["question"],
                ))
            except (KeyError, TypeError) as e:
                log.warning("dropping pending %s: missing/invalid key %s", p, e)
                continue
    return out


def _existing_answer_filled(question_path: Path) -> bool:
    if not question_path.exists():
        return False
    try:
        text = question_path.read_text(encoding="utf-8")
    except OSError:
        return False
    try:
        fm, body = parse_frontmatter(text)
    except FrontmatterError as e:
        log.warning(
            "treating %s as not-filled: corrupt frontmatter (%s)",
            question_path, e,
        )
        return False
    if "answer" in fm:
        answer = fm["answer"]
        if answer is None:
            # YAML `answer:` with no value parses as None — treat as empty.
            return False
        if not isinstance(answer, str):
            # Non-string answer (dict, list, int) means the user has
            # clearly populated the field; do not clobber.
            return True
        return bool(answer.strip())
    # Hand-edited / legacy compat: a user may have written
    # ``answer: <text>`` directly as a body line. Match only at column 0
    # so a Markdown blockquote (``> answer: x``), an indented continuation
    # of question prose, or a code-fenced example doesn't trigger a false
    # positive. Anything more ambiguous defaults to "not filled" so the
    # next write run overwrites safely.
    for line in body.splitlines():
        if line.startswith("answer:"):
            return bool(line[len("answer:"):].strip())
    return False


def write_questions_to_vault(
    pendings: list[PendingQA], vault_root: Path,
) -> WriteResult:
    questions_dir = vault_root / "questions"
    questions_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    skipped: list[Path] = []
    failed: list[Path] = []
    for pending in pendings:
        try:
            _validate_slug(pending.run_id, "run_id")
            _validate_slug(pending.worker_id, "worker_id")
            _validate_slug(pending.pending_note, "pending_note")
        except InvalidPendingSlugError as e:
            log.warning(
                "skipping pending %s/%s/%s: %s",
                pending.run_id, pending.worker_id, pending.pending_note, e,
            )
            # Synthesize a marker for the failed[] tuple so callers can see
            # which slug was rejected. Sanitize the raw value into the
            # filename so an attempted traversal cannot escape
            # questions_dir even in the report path (defense in depth —
            # these paths are not written to disk, but callers may iterate
            # them).
            raw = str(pending.pending_note)
            sanitized = "".join(c if c.isalnum() or c in "._-" else "_" for c in raw)
            failed.append(questions_dir / f"{sanitized or 'unknown'}.invalid")
            continue
        qid = f"{pending.run_id}-{pending.worker_id}-{pending.pending_note}"
        path = questions_dir / f"{qid}.md"
        if _existing_answer_filled(path):
            log.warning(
                "skipping %s: existing question file already has a filled answer",
                pending.pending_note,
            )
            skipped.append(path)
            continue
        fm = {
            "origin": pending.origin,
            "run_id": pending.run_id,
            "worker_id": pending.worker_id,
            "pending_note": pending.pending_note,
            "input_path": pending.input_path,
            "trigger": pending.trigger,
            "context": pending.context,
            "answer": "",
        }
        fm_yaml = yaml.safe_dump(fm, default_flow_style=False, sort_keys=False)
        body = (
            f"---\n{fm_yaml}---\n\n"
            f"# {pending.question}\n"
        )
        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            tmp.write_text(body, encoding="utf-8")
            tmp.replace(path)
        except OSError as e:
            log.error("failed to write question file %s: %s", path, e)
            # Best-effort cleanup of the partial tmp file.
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass
            failed.append(path)
            continue
        written.append(path)
    return WriteResult(
        written=tuple(written), skipped=tuple(skipped), failed=tuple(failed),
    )
