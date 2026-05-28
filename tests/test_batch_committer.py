from pathlib import Path

import pytest

from rufino.engine.process.batch.committer import commit
from rufino.engine.process.batch.consolidator import ConsolidationPlan
from rufino.runtime.transaction_log import TransactionLog


def _setup_run(tmp_path: Path) -> tuple[Path, Path]:
    vault = tmp_path / "vault"
    run = vault / ".rufino" / "runs" / "r1"
    (run / "workers" / "w0001" / "augmented").mkdir(parents=True)
    (run / "workers" / "w0001" / "augmented" / "n1.md").write_text(
        "---\ntitle: n1\n---\n# body\n"
    )
    (vault / "_meta").mkdir(parents=True)
    (vault / "_meta" / "_tags.md").write_text("")
    return vault, run


def test_commit_moves_and_updates(tmp_path):
    vault, run = _setup_run(tmp_path)
    plan = ConsolidationPlan(
        moves=[{"from": "workers/w0001/augmented/n1.md", "to": "apuntes/n1.md"}],
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
        moves=[{"from": "workers/w0001/augmented/n1.md", "to": "../../escape.md"}],
    )
    tx = TransactionLog(run / "commit.tx.json")
    with pytest.raises(Exception):
        commit(plan=bad, vault_root=vault, run_dir=run, tx_log=tx)

    assert (run / "workers" / "w0001" / "augmented" / "n1.md").exists()
    assert not (tmp_path / "escape.md").exists()


def test_commit_empty_plan_is_noop(tmp_path):
    vault, run = _setup_run(tmp_path)
    tx = TransactionLog(run / "commit.tx.json")
    commit(plan=ConsolidationPlan(), vault_root=vault, run_dir=run, tx_log=tx)
    assert (run / "workers" / "w0001" / "augmented" / "n1.md").exists()


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
        moves=[{"from": "workers/w0001/augmented/n1.md", "to": "apuntes/n1.md"}],
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
    assert (run / "workers" / "w0001" / "augmented" / "n1.md").exists()
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
    (run1 / "workers" / "w0001" / "augmented").mkdir(parents=True, exist_ok=True)
    plan1 = ConsolidationPlan(
        concept_writes=[{"path": "conceptos/dfs.md", "content": "V1\n", "wins_over": []}],
    )
    tx1 = TransactionLog(run1 / "commit.tx.json")
    commit(plan=plan1, vault_root=vault, run_dir=run1, tx_log=tx1)
    assert (vault / "conceptos" / "dfs.md").read_text() == "V1\n"

    # Run 2 — must succeed; baselines from run 1 must not contaminate
    run2 = vault / ".rufino" / "runs" / "r2"
    (run2 / "workers" / "w0002" / "augmented").mkdir(parents=True, exist_ok=True)
    plan2 = ConsolidationPlan(
        concept_writes=[{"path": "conceptos/dfs.md", "content": "V2\n", "wins_over": []}],
    )
    tx2 = TransactionLog(run2 / "commit.tx.json")
    commit(plan=plan2, vault_root=vault, run_dir=run2, tx_log=tx2)
    assert (vault / "conceptos" / "dfs.md").read_text() == "V2\n"

    # Rollback run 2 should restore V1 (not V0, not crash):
    tx2.rollback()
    assert (vault / "conceptos" / "dfs.md").read_text() == "V1\n"


def test_commit_snapshots_existing_destination_and_rollback_restores_old_content(tmp_path):
    """C3 codex: pre-existing dest must survive rollback when later op fails."""
    vault = tmp_path / "vault"
    run_dir = tmp_path / "run"
    (vault / "apuntes").mkdir(parents=True)
    (vault / "apuntes" / "n1.md").write_text("OLD", encoding="utf-8")

    (run_dir / "workers" / "w0001" / "augmented").mkdir(parents=True)
    (run_dir / "workers" / "w0001" / "augmented" / "n1.md").write_text("NEW", encoding="utf-8")

    plan = ConsolidationPlan(
        moves=[
            {"from": "workers/w0001/augmented/n1.md", "to": "apuntes/n1.md"},
            {"from": "workers/w0001/augmented/missing.md", "to": "apuntes/missing.md"},
        ],
        concept_writes=[], tag_index_updates=[], log_entries=[],
    )
    tx = TransactionLog(run_dir / "tx.json")
    with pytest.raises(FileNotFoundError):
        commit(plan=plan, vault_root=vault, run_dir=run_dir, tx_log=tx)

    # After rollback the OLD content must be back at the destination
    assert (vault / "apuntes" / "n1.md").read_text(encoding="utf-8") == "OLD"


def test_commit_rejects_duplicate_destinations(tmp_path):
    """Two moves cannot target the same path within one plan."""
    vault = tmp_path / "vault"
    run_dir = tmp_path / "run"
    aug = run_dir / "workers" / "w0001" / "augmented"
    aug.mkdir(parents=True)
    (aug / "a.md").write_text("A", encoding="utf-8")
    (aug / "b.md").write_text("B", encoding="utf-8")

    plan = ConsolidationPlan(
        moves=[
            {"from": "workers/w0001/augmented/a.md", "to": "apuntes/x.md"},
            {"from": "workers/w0001/augmented/b.md", "to": "apuntes/x.md"},
        ],
        concept_writes=[], tag_index_updates=[], log_entries=[],
    )
    tx = TransactionLog(run_dir / "tx.json")
    with pytest.raises(ValueError, match="duplicate destination"):
        commit(plan=plan, vault_root=vault, run_dir=run_dir, tx_log=tx)
    # Vault must be untouched
    assert not (vault / "apuntes" / "x.md").exists()


def test_commit_rejects_case_only_duplicate_destinations(tmp_path):
    """macOS APFS is case-insensitive by default — two moves whose only
    difference is letter casing collide on disk; the dedupe set must catch it."""
    vault = tmp_path / "vault"
    run_dir = tmp_path / "run"
    aug = run_dir / "workers" / "w0001" / "augmented"
    aug.mkdir(parents=True)
    (aug / "a.md").write_text("A", encoding="utf-8")
    (aug / "b.md").write_text("B", encoding="utf-8")

    plan = ConsolidationPlan(
        moves=[
            {"from": "workers/w0001/augmented/a.md", "to": "apuntes/X.md"},
            {"from": "workers/w0001/augmented/b.md", "to": "apuntes/x.md"},
        ],
        concept_writes=[], tag_index_updates=[], log_entries=[],
    )
    tx = TransactionLog(run_dir / "tx.json")
    with pytest.raises(ValueError, match="duplicate destination"):
        commit(plan=plan, vault_root=vault, run_dir=run_dir, tx_log=tx)


def test_commit_writes_authors_to_autores_dir(tmp_path):
    """Author writes from the consolidation plan land under autores/."""
    vault, run = _setup_run(tmp_path)
    plan = ConsolidationPlan(
        author_writes=[
            {
                "path": "autores/porter.md",
                "content": (
                    "---\ntipo: persona\n---\n# Michael Porter\n\nBio.\n"
                ),
                "wins_over": [],
            },
            {
                "path": "autores/drucker.md",
                "content": "---\ntipo: persona\n---\n# Peter Drucker\n",
                "wins_over": [],
            },
        ],
    )
    tx = TransactionLog(run / "commit.tx.json")
    commit(plan=plan, vault_root=vault, run_dir=run, tx_log=tx)

    assert (vault / "autores" / "porter.md").exists()
    assert (vault / "autores" / "drucker.md").exists()
    assert "Michael Porter" in (vault / "autores" / "porter.md").read_text()


def test_commit_rejects_author_write_outside_autores_dir(tmp_path):
    """author_writes targeting paths outside autores/ (apuntes/, conceptos/,
    repo root) are rejected at AuthorWrite construction time — before the
    plan even reaches commit()."""
    with pytest.raises(ValueError, match="under autores"):
        ConsolidationPlan(
            author_writes=[
                {"path": "apuntes/porter.md", "content": "X"},
            ],
        )


def test_commit_rejects_author_write_with_path_traversal(tmp_path):
    """`autores/../escape.md` is now caught at AuthorWrite construction —
    the `_reject_dot_segments` invariant kicks in before commit() ever
    receives the plan."""
    with pytest.raises(ValueError, match="must not contain '.' or '..'"):
        ConsolidationPlan(
            author_writes=[
                {"path": "autores/../escape.md", "content": "X"},
            ],
        )
    assert not (tmp_path / "escape.md").exists()


def test_commit_author_write_new_rollback_deletes_file(tmp_path, monkeypatch):
    """When a new author write succeeds but a later op fails, rollback
    must delete the freshly-created file. We inject the failure via a
    monkeypatched ``append_to_log`` (runs AFTER author_writes in commit())
    so the author file is on disk when the failure fires."""
    vault, run = _setup_run(tmp_path)
    plan = ConsolidationPlan(
        author_writes=[
            {"path": "autores/porter.md", "content": "BIO\n"},
        ],
        log_entries=["entry"],
    )

    def _boom(*args, **kwargs):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(
        "rufino.engine.process.batch.committer.append_to_log", _boom,
    )
    tx = TransactionLog(run / "commit.tx.json")
    with pytest.raises(OSError, match="simulated"):
        commit(plan=plan, vault_root=vault, run_dir=run, tx_log=tx)
    assert not (vault / "autores" / "porter.md").exists()


def test_commit_rejects_author_write_when_autores_is_symlink(tmp_path):
    """Symlink escape: if `vault/autores` is a symlink to a path INSIDE
    the vault (so `_safe_in_vault` cannot catch it), the
    `is_relative_to(autores_root)` check passes too because BOTH paths
    resolve through the same symlink — author writes silently land in
    the symlink target. Reject before any disk op.
    """
    vault, run = _setup_run(tmp_path)
    inside_decoy = vault / "decoy"
    inside_decoy.mkdir()
    (vault / "autores").symlink_to(inside_decoy)

    plan = ConsolidationPlan(
        author_writes=[
            {"path": "autores/porter.md", "content": "X"},
        ],
    )
    tx = TransactionLog(run / "commit.tx.json")
    with pytest.raises(ValueError, match="symlink"):
        commit(plan=plan, vault_root=vault, run_dir=run, tx_log=tx)
    assert not (inside_decoy / "porter.md").exists()


def test_commit_author_write_overwrites_existing_and_rollback_restores(tmp_path):
    """Overwriting an existing autores/<slug>.md must snapshot first so
    rollback restores the old content."""
    vault, run = _setup_run(tmp_path)
    (vault / "autores").mkdir(parents=True)
    (vault / "autores" / "porter.md").write_text("OLD-BIO\n", encoding="utf-8")

    plan = ConsolidationPlan(
        author_writes=[
            {"path": "autores/porter.md", "content": "NEW-BIO\n"},
        ],
    )
    tx = TransactionLog(run / "commit.tx.json")
    commit(plan=plan, vault_root=vault, run_dir=run, tx_log=tx)
    assert (vault / "autores" / "porter.md").read_text() == "NEW-BIO\n"

    tx.rollback()
    assert (vault / "autores" / "porter.md").read_text() == "OLD-BIO\n"


def test_commit_rejects_duplicate_destinations_across_concept_writes(tmp_path):
    """Dedupe must cover concept_writes (and author_writes) not only moves —
    otherwise two writes to the same path silently clobber each other."""
    vault, run = _setup_run(tmp_path)
    plan = ConsolidationPlan(
        concept_writes=[
            {"path": "conceptos/dfs.md", "content": "A"},
            {"path": "conceptos/dfs.md", "content": "B"},
        ],
    )
    tx = TransactionLog(run / "commit.tx.json")
    with pytest.raises(ValueError, match="duplicate destination"):
        commit(plan=plan, vault_root=vault, run_dir=run, tx_log=tx)


def test_commit_rejects_duplicate_destinations_across_author_writes(tmp_path):
    vault, run = _setup_run(tmp_path)
    plan = ConsolidationPlan(
        author_writes=[
            {"path": "autores/porter.md", "content": "A"},
            {"path": "autores/porter.md", "content": "B"},
        ],
    )
    tx = TransactionLog(run / "commit.tx.json")
    with pytest.raises(ValueError, match="duplicate destination"):
        commit(plan=plan, vault_root=vault, run_dir=run, tx_log=tx)


def test_commit_rejects_duplicate_destination_between_move_and_concept_write(tmp_path):
    """move.to and concept_write.path landing on the same vault path must be
    caught by the dedupe gate."""
    vault, run = _setup_run(tmp_path)
    plan = ConsolidationPlan(
        moves=[{"from": "workers/w0001/augmented/n1.md", "to": "conceptos/dfs.md"}],
        concept_writes=[{"path": "conceptos/dfs.md", "content": "Y"}],
    )
    tx = TransactionLog(run / "commit.tx.json")
    with pytest.raises(ValueError, match="duplicate destination"):
        commit(plan=plan, vault_root=vault, run_dir=run, tx_log=tx)


def test_commit_rollback_failure_chains_original_exception(
    tmp_path, monkeypatch, caplog
):
    """When rollback fails after a commit-time error, the rollback failure
    is the top-level exception (the more urgent one — vault may be in an
    inconsistent state) and the original commit error is chained via
    ``__cause__`` so the traceback shows BOTH. Both are also logged."""
    import logging as _logging

    vault, run = _setup_run(tmp_path)
    plan = ConsolidationPlan(
        moves=[
            {"from": "workers/w0001/augmented/n1.md", "to": "apuntes/n1.md"},
            {"from": "workers/w0001/augmented/missing.md", "to": "apuntes/x.md"},
        ],
    )
    tx = TransactionLog(run / "commit.tx.json")

    def _broken_rollback() -> None:
        raise RuntimeError("rollback exploded")

    monkeypatch.setattr(tx, "rollback", _broken_rollback)
    with caplog.at_level(_logging.ERROR, logger="rufino.engine.process.batch.committer"):
        with pytest.raises(RuntimeError, match="rollback exploded") as exc_info:
            commit(plan=plan, vault_root=vault, run_dir=run, tx_log=tx)
    assert isinstance(exc_info.value.__cause__, FileNotFoundError)
    assert "missing source" in str(exc_info.value.__cause__)
    assert any("rollback FAILED" in r.getMessage() for r in caplog.records)


def test_undo_move_raises_on_malformed_target():
    """Silent no-op on a malformed tx-log entry would break the all-or-nothing
    guarantee; the rollback handler must raise instead."""
    from rufino.engine.process.batch.committer import _undo_move
    with pytest.raises(ValueError, match="malformed"):
        _undo_move("no-nul-here")


def test_undo_move_overwrite_raises_on_malformed_target():
    from rufino.engine.process.batch.committer import _undo_move_overwrite
    with pytest.raises(ValueError, match="malformed"):
        _undo_move_overwrite("only\x00two")


def test_undo_snapshot_restore_raises_on_malformed_target():
    from rufino.engine.process.batch.committer import _undo_snapshot_restore
    with pytest.raises(ValueError, match="malformed"):
        _undo_snapshot_restore("no-nul")


def test_undo_log_append_raises_on_malformed_target():
    from rufino.engine.process.batch.committer import _undo_log_append
    with pytest.raises(ValueError, match="malformed"):
        _undo_log_append("only\x00two")


def test_undo_log_append_deletes_log_when_did_not_pre_exist(tmp_path):
    """The 'existed=0' branch: rollback must delete a log file that the
    commit created from scratch, not leave a stale empty file behind."""
    from rufino.engine.process.batch.committer import _undo_log_append
    live = tmp_path / "_processing-log.md"
    live.write_text("created during commit\n", encoding="utf-8")
    snap = tmp_path / "log.snap"
    snap.write_text("", encoding="utf-8")
    _undo_log_append(f"{live}\x00{snap}\x000")
    assert not live.exists()


def test_undo_log_append_restores_log_when_pre_existed(tmp_path):
    """The 'existed=1' branch: restore from snapshot."""
    from rufino.engine.process.batch.committer import _undo_log_append
    live = tmp_path / "_processing-log.md"
    live.write_text("NEW", encoding="utf-8")
    snap = tmp_path / "log.snap"
    snap.write_text("OLD", encoding="utf-8")
    _undo_log_append(f"{live}\x00{snap}\x001")
    assert live.read_text(encoding="utf-8") == "OLD"


def test_undo_log_append_raises_on_corrupt_existed_token(tmp_path):
    """`existed` not in (0, 1) is a malformed entry — must raise, not no-op.
    Silent no-op would leave the log file with whatever the failed commit
    appended, breaking the all-or-nothing rollback guarantee."""
    from rufino.engine.process.batch.committer import _undo_log_append
    live = tmp_path / "_processing-log.md"
    snap = tmp_path / "log.snap"
    with pytest.raises(ValueError, match="'existed' token"):
        _undo_log_append(f"{live}\x00{snap}\x00True")
    with pytest.raises(ValueError, match="'existed' token"):
        _undo_log_append(f"{live}\x00{snap}\x002")


def test_committer_nul_encoded_target_survives_json_roundtrip(tmp_path):
    """H7: rollback after reload from disk must still parse \\x00-encoded target."""
    vault = tmp_path / "vault"
    run_dir = tmp_path / "run"
    (vault / "apuntes").mkdir(parents=True)
    (vault / "apuntes" / "n1.md").write_text("OLD", encoding="utf-8")
    aug = run_dir / "workers" / "w0001" / "augmented"
    aug.mkdir(parents=True)
    (aug / "n1.md").write_text("NEW", encoding="utf-8")

    plan = ConsolidationPlan(
        moves=[{"from": "workers/w0001/augmented/n1.md", "to": "apuntes/n1.md"}],
        concept_writes=[], tag_index_updates=[], log_entries=[],
    )
    tx_path = run_dir / "tx.json"
    tx = TransactionLog(tx_path)
    commit(plan=plan, vault_root=vault, run_dir=run_dir, tx_log=tx)

    # Reload tx_log from disk and rollback
    reloaded = TransactionLog.load(tx_path)
    reloaded.rollback()
    assert (vault / "apuntes" / "n1.md").read_text(encoding="utf-8") == "OLD"
