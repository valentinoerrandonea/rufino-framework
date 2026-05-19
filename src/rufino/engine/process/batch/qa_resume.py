"""Resume a process-batch Q&A: re-invoke a single-note worker with the
user's answer injected, then archive the question on success.
"""
import json
import os
import shutil
from pathlib import Path

import yaml

from rufino.engine.process.batch.dispatcher import (
    SESSION_EXPIRED_EXIT_CODE,
    build_argv,
)
from rufino.engine.process.batch.errors import WorkerSessionExpiredError
from rufino.engine.process.batch.planner import WorkerAssignment
from rufino.engine.process.batch.runner_helper import run_claude
from rufino.engine.process.batch.validator import validate_one
from rufino.engine.process.batch.worker_prompt import (
    build_worker_system_prompt,
)
from rufino.engine.process.manifest import parse_worker_manifest


def _read_question(qfile: Path) -> dict:
    text = qfile.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    _, fm_text, body = text.split("---", 2)
    fm = yaml.safe_load(fm_text) or {}
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
    meta = _read_question(question_file)
    if not meta.get("answer"):
        return False
    if meta.get("origin") != "process-batch":
        return False
    run_id = meta["run_id"]
    worker_id = meta["worker_id"]
    slug = meta["pending_note"]
    run_dir = vault_root / ".rufino" / "runs" / run_id
    if not run_dir.exists():
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

    inbox = run_dir / "inbox"
    matches = list(inbox.rglob(f"{slug}.md")) + list(inbox.rglob(f"{slug}.pdf"))
    if not matches:
        return False
    note_path = matches[0]

    staging_dir = run_dir / "workers" / worker_id
    staging_dir.mkdir(parents=True, exist_ok=True)
    assignment = WorkerAssignment(
        worker_id=worker_id, group=note_path.parent.name, notes=(note_path,),
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

    env = os.environ.copy()
    env["FAKE_CLAUDE_NOTES"] = str(note_path)
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

    pending = staging_dir / "pending" / f"{slug}.json"
    if pending.exists():
        pending.unlink()

    aug = staging_dir / "augmented" / f"{slug}.md"
    delta = staging_dir / "deltas" / f"{slug}.json"
    if not aug.exists():
        return False
    validation = validate_one(aug, delta, manifest)
    if not validation.passed:
        return False

    archived = vault_root / "questions" / "answered"
    archived.mkdir(parents=True, exist_ok=True)
    shutil.move(str(question_file), archived / question_file.name)
    return True
