"""Collect pending Q&A blocks emitted by workers and write them to the vault.

Workers can decide a note triggers a qa_trigger from the adapter; in that case
they write `pending/<slug>.json` in their staging dir instead of the usual
augmented/+deltas/ pair. Rufino, after VALIDATE, scans for these and writes
a Q&A note into the vault's `questions/` directory.
"""
import json
from dataclasses import dataclass
from pathlib import Path


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
            except json.JSONDecodeError:
                continue
            try:
                out.append(PendingQA(
                    origin=data["origin"], run_id=data["run_id"],
                    worker_id=data["worker_id"], pending_note=data["pending_note"],
                    input_path=data["input_path"], trigger=data["trigger"],
                    context=data.get("context", ""), question=data["question"],
                ))
            except KeyError:
                continue
    return out


def write_questions_to_vault(
    pendings: list[PendingQA], vault_root: Path,
) -> list[Path]:
    questions_dir = vault_root / "questions"
    questions_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for pending in pendings:
        qid = f"{pending.run_id}-{pending.worker_id}-{pending.pending_note}"
        path = questions_dir / f"{qid}.md"
        body = (
            "---\n"
            f"origin: {pending.origin}\n"
            f"run_id: {pending.run_id}\n"
            f"worker_id: {pending.worker_id}\n"
            f"pending_note: {pending.pending_note}\n"
            f"input_path: {pending.input_path}\n"
            f"trigger: {pending.trigger}\n"
            f"context: {pending.context!r}\n"
            "---\n\n"
            f"# {pending.question}\n\n"
            "answer: \n"
        )
        path.write_text(body, encoding="utf-8")
        written.append(path)
    return written
