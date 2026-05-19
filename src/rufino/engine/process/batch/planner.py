"""Build an execution Plan from a StagedCorpus.

Adaptive batching: each group gets 1 worker if it has <= batch_size notes,
otherwise it is split into ceil(n / batch_size) consecutive chunks.
"""
import json
import math
from dataclasses import dataclass
from pathlib import Path

from rufino.engine.process.batch.stager import StagedCorpus


@dataclass(frozen=True)
class WorkerAssignment:
    worker_id: str
    group: str
    notes: tuple[Path, ...]


@dataclass(frozen=True)
class Plan:
    run_id: str
    adapter_dir: str
    workers: tuple[WorkerAssignment, ...]

    def to_json(self) -> str:
        return json.dumps(
            {
                "run_id": self.run_id,
                "adapter_dir": self.adapter_dir,
                "workers": [
                    {
                        "worker_id": w.worker_id,
                        "group": w.group,
                        "notes": [str(p) for p in w.notes],
                    }
                    for w in self.workers
                ],
            },
            indent=2,
        )


def build_plan(
    staged: StagedCorpus,
    *,
    run_id: str,
    adapter_dir: str,
    batch_size: int,
) -> Plan:
    if batch_size < 1:
        raise ValueError(f"batch_size must be >= 1, got {batch_size}")

    workers: list[WorkerAssignment] = []
    counter = 1
    for group in sorted(staged.groups):
        notes = list(staged.groups[group])
        if not notes:
            continue
        if len(notes) <= batch_size:
            workers.append(WorkerAssignment(
                worker_id=f"w{counter:04d}",
                group=group,
                notes=tuple(notes),
            ))
            counter += 1
            continue
        chunks = math.ceil(len(notes) / batch_size)
        for chunk_idx in range(chunks):
            slice_ = notes[chunk_idx * batch_size : (chunk_idx + 1) * batch_size]
            workers.append(WorkerAssignment(
                worker_id=f"w{counter:04d}",
                group=group,
                notes=tuple(slice_),
            ))
            counter += 1
    return Plan(run_id=run_id, adapter_dir=adapter_dir, workers=tuple(workers))
