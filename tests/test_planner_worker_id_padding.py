"""Worker IDs use :04d padding so a corpus producing 1000-9999 workers does
not collide. v0.1 used :03d and capped at w999."""
from pathlib import Path

from rufino.engine.process.batch.planner import build_plan
from rufino.engine.process.batch.stager import StagedCorpus


def _staged_with_n_groups(n: int, tmp_path: Path) -> StagedCorpus:
    groups: dict[str, list[Path]] = {}
    for i in range(n):
        group = f"g{i:05d}"
        note = tmp_path / f"{group}.md"
        note.write_text("# x\n", encoding="utf-8")
        groups[group] = [note]
    return StagedCorpus(groups=groups, skipped=[])


def test_worker_id_is_padded_to_four_digits(tmp_path: Path) -> None:
    staged = _staged_with_n_groups(3, tmp_path)
    plan = build_plan(staged, run_id="r", adapter_dir="/x", batch_size=1)
    assert plan.workers[0].worker_id == "w0001"
    assert plan.workers[1].worker_id == "w0002"
    assert plan.workers[2].worker_id == "w0003"


def test_worker_id_supports_thousands(tmp_path: Path) -> None:
    staged = _staged_with_n_groups(1500, tmp_path)
    plan = build_plan(staged, run_id="r", adapter_dir="/x", batch_size=1)
    assert len(plan.workers) == 1500
    assert plan.workers[0].worker_id == "w0001"
    assert plan.workers[999].worker_id == "w1000"
    assert plan.workers[1499].worker_id == "w1500"
    # All IDs identical length (avoids lexicographic-sort surprises).
    assert len({len(w.worker_id) for w in plan.workers}) == 1
