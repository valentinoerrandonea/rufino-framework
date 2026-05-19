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


def test_commit_rejects_escape_in_move_from(tmp_path):
    """H3: m['from'] must be validated to stay inside run_dir."""
    vault, run = _setup_run(tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text("secret\n")
    bad = ConsolidationPlan(
        moves=[{"from": "../../../outside.md", "to": "apuntes/x.md"}],
    )
    tx = TransactionLog(run / "commit.tx.json")
    with pytest.raises(ValueError, match="run_dir"):
        commit(plan=bad, vault_root=vault, run_dir=run, tx_log=tx)
    assert outside.exists()
    assert not (vault / "apuntes" / "x.md").exists()


def test_rollback_after_successful_commit_reverts_all_categories(tmp_path):
    """C1 + H1 + M3: rollback after a complete commit must revert moves,
    concept writes, tag index updates, and log entries without crashing.
    """
    vault, run = _setup_run(tmp_path)
    (vault / "_meta" / "_tags.md").write_text("# Tags\n- existing\n")
    (vault / "conceptos").mkdir(parents=True)
    (vault / "conceptos" / "dfs.md").write_text("PRE-EXISTING\n")

    plan = ConsolidationPlan(
        moves=[{"from": "workers/w001/augmented/n1.md", "to": "apuntes/n1.md"}],
        concept_writes=[{"path": "conceptos/dfs.md", "content": "# DFS NEW\n", "wins_over": []}],
        tag_index_updates=[{"tag": "materia/math", "notes": ["n1"]}],
        log_entries=["batch r1 ok"],
    )
    tx = TransactionLog(run / "commit.tx.json")
    commit(plan=plan, vault_root=vault, run_dir=run, tx_log=tx)

    # All applied:
    assert (vault / "apuntes" / "n1.md").exists()
    assert (vault / "conceptos" / "dfs.md").read_text() == "# DFS NEW\n"
    assert "materia/math" in (vault / "_meta" / "_tags.md").read_text()
    assert "batch r1 ok" in (vault / "_meta" / "_processing-log.md").read_text()

    # Manual rollback after success must not crash:
    tx.rollback()

    # Everything restored:
    assert (run / "workers" / "w001" / "augmented" / "n1.md").exists()
    assert not (vault / "apuntes" / "n1.md").exists()
    assert (vault / "conceptos" / "dfs.md").read_text() == "PRE-EXISTING\n"
    assert (vault / "_meta" / "_tags.md").read_text() == "# Tags\n- existing\n"
    # Log was created fresh (didn't exist before), so rollback should remove it:
    assert not (vault / "_meta" / "_processing-log.md").exists()


def test_commit_does_not_leak_backups_into_vault(tmp_path):
    """H2: snapshots used for rollback must live outside the vault."""
    vault, run = _setup_run(tmp_path)
    (vault / "conceptos").mkdir(parents=True)
    (vault / "conceptos" / "dfs.md").write_text("OLD\n")

    plan = ConsolidationPlan(
        concept_writes=[{"path": "conceptos/dfs.md", "content": "NEW\n", "wins_over": []}],
        tag_index_updates=[{"tag": "x", "notes": ["n"]}],
    )
    tx = TransactionLog(run / "commit.tx.json")
    commit(plan=plan, vault_root=vault, run_dir=run, tx_log=tx)

    # No stray .pre-batch files anywhere in the vault tree (excluding run_dir, which
    # is inside .rufino/ and is committer-private):
    leaked = [
        p for p in vault.rglob("*.pre-batch")
        if ".rufino" not in p.parts
    ]
    assert leaked == [], f"snapshots leaked into vault: {leaked}"


def test_commit_succeeds_when_run_twice_with_overwrites(tmp_path):
    """H2 follow-on: two sequential commits both with concept overwrites must
    not corrupt the rollback chain — each run_dir is isolated."""
    vault, _ = _setup_run(tmp_path)
    (vault / "conceptos").mkdir(parents=True)
    (vault / "conceptos" / "dfs.md").write_text("V0\n")

    # Run 1
    run1 = vault / ".rufino" / "runs" / "r1"
    (run1 / "workers" / "w001" / "augmented").mkdir(parents=True, exist_ok=True)
    plan1 = ConsolidationPlan(
        concept_writes=[{"path": "conceptos/dfs.md", "content": "V1\n", "wins_over": []}],
    )
    tx1 = TransactionLog(run1 / "commit.tx.json")
    commit(plan=plan1, vault_root=vault, run_dir=run1, tx_log=tx1)
    assert (vault / "conceptos" / "dfs.md").read_text() == "V1\n"

    # Run 2 — must succeed; baselines from run 1 must not contaminate
    run2 = vault / ".rufino" / "runs" / "r2"
    (run2 / "workers" / "w002" / "augmented").mkdir(parents=True, exist_ok=True)
    plan2 = ConsolidationPlan(
        concept_writes=[{"path": "conceptos/dfs.md", "content": "V2\n", "wins_over": []}],
    )
    tx2 = TransactionLog(run2 / "commit.tx.json")
    commit(plan=plan2, vault_root=vault, run_dir=run2, tx_log=tx2)
    assert (vault / "conceptos" / "dfs.md").read_text() == "V2\n"

    # Rollback run 2 should restore V1 (not V0, not crash):
    tx2.rollback()
    assert (vault / "conceptos" / "dfs.md").read_text() == "V1\n"
