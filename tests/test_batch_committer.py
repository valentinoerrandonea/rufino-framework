import json
from pathlib import Path

import pytest

from rufino.engine.process.batch.committer import commit
from rufino.engine.process.batch.consolidator import ConsolidationPlan
from rufino.runtime.transaction_log import TransactionLog


def _setup_run(tmp_path: Path) -> tuple[Path, Path]:
    vault = tmp_path / "vault"
    run = vault / ".rufino" / "runs" / "r1"
    (run / "workers" / "w001" / "augmented").mkdir(parents=True)
    (run / "workers" / "w001" / "augmented" / "n1.md").write_text(
        "---\ntitle: n1\n---\n# body\n"
    )
    (vault / "_meta").mkdir(parents=True)
    (vault / "_meta" / "_tags.md").write_text("")
    return vault, run


def test_commit_moves_and_updates(tmp_path):
    vault, run = _setup_run(tmp_path)
    plan = ConsolidationPlan(
        moves=[{"from": "workers/w001/augmented/n1.md", "to": "apuntes/n1.md"}],
        concept_writes=[{"path": "conceptos/dfs.md", "content": "# DFS\n", "wins_over": []}],
        tag_index_updates=[{"tag": "materia/math", "notes": ["n1"]}],
        log_entries=["batch r1 ok"],
    )
    tx = TransactionLog(run / "commit.tx.json")
    commit(plan=plan, vault_root=vault, run_dir=run, tx_log=tx)

    assert (vault / "apuntes" / "n1.md").exists()
    assert (vault / "conceptos" / "dfs.md").read_text() == "# DFS\n"
    tags = (vault / "_meta" / "_tags.md").read_text()
    assert "materia/math" in tags
    assert "n1" in tags
    log = (vault / "_meta" / "_processing-log.md").read_text()
    assert "batch r1 ok" in log


def test_commit_rolls_back_on_escape(tmp_path):
    vault, run = _setup_run(tmp_path)
    bad = ConsolidationPlan(
        moves=[{"from": "workers/w001/augmented/n1.md", "to": "../../escape.md"}],
    )
    tx = TransactionLog(run / "commit.tx.json")
    with pytest.raises(Exception):
        commit(plan=bad, vault_root=vault, run_dir=run, tx_log=tx)

    assert (run / "workers" / "w001" / "augmented" / "n1.md").exists()
    assert not (tmp_path / "escape.md").exists()


def test_commit_empty_plan_is_noop(tmp_path):
    vault, run = _setup_run(tmp_path)
    tx = TransactionLog(run / "commit.tx.json")
    commit(plan=ConsolidationPlan(), vault_root=vault, run_dir=run, tx_log=tx)
    assert (run / "workers" / "w001" / "augmented" / "n1.md").exists()
