"""Resume a process-batch Q&A: re-invoke a single-note worker with the
user's answer injected, then VALIDATE and COMMIT the augmented note to
the vault canon before archiving the question.

The question file lives at ``<vault>/questions/<basename>.md`` with
frontmatter pointing back to the originating run (``run_id``,
``worker_id``, ``pending_note``). Those identifiers are treated as
**untrusted input** — the question file is hand-editable by the user and
must not be allowed to redirect Rufino into writing outside the vault.
"""
import json
import logging
import os
import re
import shutil
import uuid
from pathlib import Path

import yaml

from rufino.engine.process.batch.committer import commit
from rufino.engine.process.batch.consolidator import ConsolidationPlan
from rufino.engine.process.batch.dispatcher import (
    SESSION_EXPIRED_EXIT_CODE,
    build_argv,
)
from rufino.engine.process.batch.errors import (
    BatchError,
    WorkerSessionExpiredError,
)
from rufino.engine.process.batch.planner import WorkerAssignment
from rufino.engine.process.batch.retry import _write_single_note_assignment
from rufino.engine.process.batch.runner_helper import run_claude
from rufino.engine.process.batch.validator import validate_one
from rufino.engine.process.batch.worker_prompt import (
    build_worker_system_prompt,
)
from rufino.engine.process.helpers.frontmatter import parse_frontmatter
from rufino.engine.process.manifest import parse_worker_manifest
from rufino.runtime.transaction_log import TransactionLog


log = logging.getLogger(__name__)


_PASSTHROUGH_EXTS = (".md", ".pdf", ".txt")
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]+$")


def _assert_safe_id(value: object, *, field: str) -> str:
    """Refuse anything that could escape the run/worker directory.

    Raises ``BatchError`` (not ``ValueError``) so callers can distinguish
    user-controlled bad input from internal logic errors.
    """
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise BatchError(
            f"unsafe identifier in question frontmatter ({field}={value!r})"
        )
    return value


def _read_question(qfile: Path) -> dict:
    """Parse a question file.

    Prefers ``answer`` from the frontmatter (post-v0.1.0 layout written by
    ``qa_pending``); falls back to a body line ``answer: ...`` so legacy
    question files written before commit ``8f3b677`` still resume.
    """
    text = qfile.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    _, fm_text, body = text.split("---", 2)
    fm = yaml.safe_load(fm_text) or {}
    fm_answer = fm.get("answer")
    if isinstance(fm_answer, str) and fm_answer.strip():
        fm["answer"] = fm_answer.strip()
        return fm
    answer = ""
    for line in body.splitlines():
        if line.strip().startswith("answer:"):
            answer = line.split(":", 1)[1].strip()
            break
    fm["answer"] = answer
    return fm


_RESUME_APPENDIX = """

ANSWERED

El usuario respondió la pregunta de Q&A. Información:

  - trigger: {trigger}
  - contexto guardado: {context}
  - respuesta del usuario: {answer}

Rehacé esta nota con la respuesta integrada. Output normal: augmented/<slug>.md
y deltas/<slug>.json.
"""


async def resume_pending_qa(
    *, vault_root: Path, question_file: Path,
) -> bool:
    """Re-run the worker with the answer appended, validate, commit, archive.

    Returns ``True`` on a successful resume (note now lives in the vault
    canon and the question is in ``questions/answered/``), ``False`` for
    benign skip conditions (no answer yet, wrong origin, missing run dir,
    worker output absent or invalid). Raises ``BatchError`` only when the
    question file itself is malformed in a security-sensitive way.
    """
    meta = _read_question(question_file)
    if not meta.get("answer"):
        return False
    if meta.get("origin") != "process-batch":
        return False

    # Sanitize *before* touching the filesystem. A malicious YAML
    # ``run_id: ../../../etc`` must never be joined into a path.
    run_id = _assert_safe_id(meta.get("run_id"), field="run_id")
    worker_id = _assert_safe_id(meta.get("worker_id"), field="worker_id")
    slug = _assert_safe_id(meta.get("pending_note"), field="pending_note")

    run_dir = vault_root / ".rufino" / "runs" / run_id
    if not run_dir.exists():
        log.warning(
            "qa-resume: run_dir for %s no longer exists; leaving question",
            run_id,
        )
        return False

    plan_data = json.loads((run_dir / "plan.json").read_text(encoding="utf-8"))
    adapter_dir = Path(plan_data["adapter_dir"])
    manifest = parse_worker_manifest(
        (adapter_dir / "manifest.yaml").read_text(encoding="utf-8")
    )
    adapter_prompt = (
        (adapter_dir / "prompt.md").read_text(encoding="utf-8")
        if (adapter_dir / "prompt.md").exists() else ""
    )

    # Locate the source note. ``input_path`` is also user-controlled, so
    # confine the candidate to ``run_dir`` via resolve().is_relative_to().
    inbox = run_dir / "inbox"
    note_path: Path | None = None
    declared_input = meta.get("input_path")
    if isinstance(declared_input, str):
        candidate = run_dir / declared_input
        if (
            candidate.exists()
            and candidate.resolve().is_relative_to(run_dir.resolve())
        ):
            note_path = candidate
    if note_path is None:
        matches: list[Path] = []
        for ext in _PASSTHROUGH_EXTS:
            matches.extend(inbox.rglob(f"{slug}{ext}"))
        if not matches:
            log.warning(
                "qa-resume cannot locate note for slug=%s (run=%s); skipping",
                slug, run_id,
            )
            return False
        note_path = matches[0]

    staging_dir = run_dir / "workers" / worker_id
    staging_dir.mkdir(parents=True, exist_ok=True)
    # Clear stale leftovers so we don't falsely succeed on a previous
    # invocation's file when the worker now silently produces nothing.
    for stale in (
        staging_dir / "augmented" / f"{slug}.md",
        staging_dir / "deltas" / f"{slug}.json",
        staging_dir / "pending" / f"{slug}.json",
    ):
        if stale.exists():
            stale.unlink()

    assignment = WorkerAssignment(
        worker_id=worker_id,
        group=note_path.parent.name,
        notes=(note_path,),
    )
    _write_single_note_assignment(
        staging_dir, assignment, run_id=run_id, note_path=note_path,
    )

    base_prompt = build_worker_system_prompt(
        manifest=manifest, adapter_prompt_text=adapter_prompt,
        assignment=assignment, vault_slug="",
        staging_dir=staging_dir, vault_concepts_top_n=[],
        run_id=run_id,
    )
    appendix = _RESUME_APPENDIX.format(
        trigger=meta.get("trigger", ""),
        context=meta.get("context", ""),
        answer=meta["answer"],
    )

    # Inherit os.environ but DO NOT set FAKE_CLAUDE_NOTES — that was a
    # test-only leak that real ``claude`` ignores and that masked the
    # missing assignment.json write before this refactor.
    env = os.environ.copy()
    argv = build_argv(
        system_prompt=base_prompt + appendix,
        vault_slug="",
    )
    result = await run_claude(
        argv=argv, cwd=staging_dir, env=env, timeout_seconds=300.0,
    )
    if result.exit_code == SESSION_EXPIRED_EXIT_CODE:
        raise WorkerSessionExpiredError(
            "Tu sesión Claude está expirada. Corré `claude login`."
        )
    if result.exit_code != 0:
        log.warning(
            "qa-resume worker exited %d for %s (run=%s): %s",
            result.exit_code, slug, run_id, result.stderr[:500],
        )
        return False

    aug = staging_dir / "augmented" / f"{slug}.md"
    delta = staging_dir / "deltas" / f"{slug}.json"
    if not aug.exists():
        log.warning(
            "qa-resume worker produced no augmented/%s.md (run=%s); "
            "leaving question in place",
            slug, run_id,
        )
        return False
    validation = validate_one(aug, delta, manifest)
    if not validation.passed:
        log.warning(
            "qa-resume validation failed for %s (run=%s): %s",
            slug, run_id, list(validation.errors),
        )
        return False

    # COMMIT the resumed note to the vault canon via the same path as
    # the regular batch commit so rollback semantics are identical.
    fm, _ = parse_frontmatter(aug.read_text(encoding="utf-8"))
    variables = {k: v for k, v in fm.items() if isinstance(v, str)}
    variables.setdefault("slug", slug)
    try:
        dest_rel = manifest.destination_path.format(**variables)
    except KeyError as e:
        log.warning(
            "qa-resume cannot compute destination for %s: "
            "missing template key %s",
            slug, e,
        )
        return False

    rel_from = aug.relative_to(run_dir)
    plan = ConsolidationPlan(
        moves=[{"from": str(rel_from), "to": dest_rel}],
        concept_writes=[],
        tag_index_updates=[],
        log_entries=[f"batch-qa-resume run={run_id} slug={slug}"],
    )
    # Unique tx-log path per attempt so two qa-poll runs (manual + launchd
    # tick, retry after a hung worker, etc.) don't clobber each other's
    # rollback log if they race on the same slug.
    tx_suffix = uuid.uuid4().hex[:8]
    tx = TransactionLog(run_dir / f"qa-resume-{slug}.{tx_suffix}.tx.json")
    try:
        commit(plan=plan, vault_root=vault_root, run_dir=run_dir, tx_log=tx)
    except WorkerSessionExpiredError:
        # Surface auth failures — qa-poll's caller (CLI) decides what to do.
        raise
    except Exception as e:  # commit already rolled back internally
        log.warning(
            "qa-resume commit failed for %s (run=%s): %s",
            slug, run_id, e,
        )
        return False

    # Archive the question ONLY after the commit succeeded — if commit
    # rolls back, the question stays in ``questions/`` so qa-poll can
    # try again next tick.
    archived = vault_root / "questions" / "answered"
    archived.mkdir(parents=True, exist_ok=True)
    shutil.move(str(question_file), archived / question_file.name)
    return True
