import json
from pathlib import Path

import pytest

from rufino.engine.process.batch.planner import (
    Plan,
    WorkerAssignment,
    build_plan,
)
from rufino.engine.process.batch.stager import StagedCorpus


def _fake_paths(group: str, n: int, tmp_path: Path) -> list[Path]:
    out = []
    for i in range(n):
        p = tmp_path / "inbox" / group / f"note-{i:03d}.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# n\n")
        out.append(p)
    return out


def test_single_small_group_yields_one_worker(tmp_path):
    notes = _fake_paths("math", 3, tmp_path)
    staged = StagedCorpus(groups={"math": notes})
    plan = build_plan(staged, run_id="r1", adapter_dir="/a", batch_size=10)
    assert len(plan.workers) == 1
    assert plan.workers[0].group == "math"
    assert plan.workers[0].notes == tuple(notes)


def test_group_above_batch_size_splits(tmp_path):
    notes = _fake_paths("math", 25, tmp_path)
    staged = StagedCorpus(groups={"math": notes})
    plan = build_plan(staged, run_id="r1", adapter_dir="/a", batch_size=10)
    assert len(plan.workers) == 3
    sizes = [len(w.notes) for w in plan.workers]
    assert sizes == [10, 10, 5]
    assert all(w.group == "math" for w in plan.workers)


def test_multiple_groups_independent(tmp_path):
    a = _fake_paths("math", 4, tmp_path)
    b = _fake_paths("hist", 12, tmp_path)
    staged = StagedCorpus(groups={"math": a, "hist": b})
    plan = build_plan(staged, run_id="r1", adapter_dir="/a", batch_size=10)
    assert len(plan.workers) == 3
    by_group: dict[str, list] = {}
    for w in plan.workers:
        by_group.setdefault(w.group, []).append(w)
    assert len(by_group["math"]) == 1
    assert len(by_group["hist"]) == 2


def test_worker_ids_are_unique_and_stable(tmp_path):
    notes = _fake_paths("math", 25, tmp_path)
    plan = build_plan(
        StagedCorpus(groups={"math": notes}),
        run_id="r1", adapter_dir="/a", batch_size=10,
    )
    ids = [w.worker_id for w in plan.workers]
    assert ids == ["w001", "w002", "w003"]


def test_empty_corpus_yields_empty_plan(tmp_path):
    plan = build_plan(StagedCorpus(), run_id="r1", adapter_dir="/a", batch_size=10)
    assert plan.workers == ()


def test_plan_serialises_to_json(tmp_path):
    notes = _fake_paths("math", 2, tmp_path)
    plan = build_plan(
        StagedCorpus(groups={"math": notes}),
        run_id="r1", adapter_dir="/a", batch_size=10,
    )
    s = plan.to_json()
    parsed = json.loads(s)
    assert parsed["run_id"] == "r1"
    assert parsed["adapter_dir"] == "/a"
    assert len(parsed["workers"]) == 1
    assert parsed["workers"][0]["worker_id"] == "w001"
    assert len(parsed["workers"][0]["notes"]) == 2
