"""Apply a ConsolidationPlan to the vault via the transaction log.

All snapshots used for rollback live under ``run_dir/.backups/`` so they
never leak into the user's vault tree. Rollback handlers are module-level
and receive their full state encoded in ``LogEntry.target``; closures
with default-arg state would be silently overwritten because the registry
invokes handlers positionally.
"""
import shutil
import uuid
from pathlib import Path

from rufino.engine.process.batch.consolidator import ConsolidationPlan
from rufino.engine.process.helpers.indices import (
    append_to_log,
    update_tag_index,
)
from rufino.runtime.transaction_log import (
    TransactionLog,
    apply_and_log,
    register_rollback,
)


_NUL = "\x00"


def _safe_in_root(root: Path, rel: str, *, label: str) -> Path:
    target = (root / rel).resolve()
    root_resolved = root.resolve()
    if not target.is_relative_to(root_resolved):
        raise ValueError(f"path escapes {label}: {rel!r}")
    return target


def _safe_in_vault(vault_root: Path, rel: str) -> Path:
    return _safe_in_root(vault_root, rel, label="vault")


def _safe_in_run_dir(run_dir: Path, rel: str) -> Path:
    return _safe_in_root(run_dir, rel, label="run_dir")


def _undo_move(target: str) -> None:
    if _NUL not in target:
        return
    dest, src = target.split(_NUL, 1)
    if Path(dest).exists():
        Path(src).parent.mkdir(parents=True, exist_ok=True)
        shutil.move(dest, src)


def _undo_move_overwrite(target: str) -> None:
    """Restore dest from snap, then move dest back to src. Target format:
    ``"<dest>\\x00<src>\\x00<snap>"``.

    Snap-only fallback only runs when ``src`` does not already hold content —
    otherwise we would silently clobber whatever lives at src.
    """
    parts = target.split(_NUL)
    if len(parts) != 3:
        return
    dest, src, snap = parts
    dest_p, src_p, snap_p = Path(dest), Path(src), Path(snap)
    if dest_p.exists() and snap_p.exists():
        src_p.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(dest, src)
        shutil.copy2(snap, dest)
    elif snap_p.exists() and not src_p.exists():
        shutil.copy2(snap, dest)


def _undo_snapshot_restore(target: str) -> None:
    """Restore ``live`` from ``snap``. Target format: ``"<live>\\x00<snap>"``."""
    if _NUL not in target:
        return
    live, snap = target.split(_NUL, 1)
    if Path(snap).exists():
        shutil.copy2(snap, live)


def _undo_log_append(target: str) -> None:
    """Restore log file from snapshot, or delete it if it did not pre-exist.

    Target format: ``"<live>\\x00<snap>\\x00<existed>"`` where ``existed``
    is ``"1"`` or ``"0"``.
    """
    parts = target.split(_NUL)
    if len(parts) != 3:
        return
    live, snap, existed = parts
    live_p = Path(live)
    snap_p = Path(snap)
    if existed == "1" and snap_p.exists():
        shutil.copy2(snap_p, live_p)
    elif existed == "0" and live_p.exists():
        live_p.unlink()


register_rollback("batch_undo_move", _undo_move)
register_rollback("batch_undo_move_overwrite", _undo_move_overwrite)
register_rollback("batch_undo_snapshot_restore", _undo_snapshot_restore)
register_rollback("batch_undo_log_append", _undo_log_append)


def _new_backup_path(run_dir: Path, hint: str) -> Path:
    """Allocate a unique snapshot path inside ``run_dir/.backups/``."""
    backups = run_dir / ".backups"
    backups.mkdir(parents=True, exist_ok=True)
    return backups / f"{hint}.{uuid.uuid4().hex[:8]}.snap"


def commit(
    *,
    plan: ConsolidationPlan,
    vault_root: Path,
    run_dir: Path,
    tx_log: TransactionLog,
) -> None:
    """Apply plan via tx_log. On any failure, rollback restores state and the
    exception propagates."""
    # Reject duplicate destinations before any disk op. Lowercase the key so
    # case-insensitive filesystems (macOS APFS default, Windows NTFS) don't
    # let "apuntes/X.md" and "apuntes/x.md" slip through and silently
    # overwrite each other on disk. ``os.path.normcase`` is a no-op on POSIX
    # so it can't be used here.
    seen: set[str] = set()
    for m in plan.moves:
        key = m["to"].lower()
        if key in seen:
            raise ValueError(f"duplicate destination in plan: {m['to']!r}")
        seen.add(key)

    try:
        for m in plan.moves:
            src = _safe_in_run_dir(run_dir, m["from"])
            dest = _safe_in_vault(vault_root, m["to"])
            if not src.exists():
                raise FileNotFoundError(f"missing source: {src}")
            dest.parent.mkdir(parents=True, exist_ok=True)

            if dest.exists():
                snap = _new_backup_path(run_dir, dest.stem)
                shutil.copy2(dest, snap)

                def _do_move(src=src, dest=dest) -> None:
                    shutil.move(str(src), str(dest))

                apply_and_log(
                    tx_log,
                    op="batch_move_overwrite",
                    target=f"{dest}{_NUL}{src}{_NUL}{snap}",
                    apply_fn=_do_move,
                    rollback="batch_undo_move_overwrite",
                )
            else:
                def _do_move(src=src, dest=dest) -> None:
                    shutil.move(str(src), str(dest))

                apply_and_log(
                    tx_log,
                    op="batch_move",
                    target=f"{dest}{_NUL}{src}",
                    apply_fn=_do_move,
                    rollback="batch_undo_move",
                )

        for cw in plan.concept_writes:
            dest = _safe_in_vault(vault_root, cw["path"])
            dest.parent.mkdir(parents=True, exist_ok=True)
            content = cw["content"]

            def _do_write(dest=dest, content=content) -> None:
                dest.write_text(content, encoding="utf-8")

            if dest.exists():
                snap = _new_backup_path(run_dir, dest.stem)
                shutil.copy2(dest, snap)
                apply_and_log(
                    tx_log,
                    op="batch_concept_write_overwrite",
                    target=f"{dest}{_NUL}{snap}",
                    apply_fn=_do_write,
                    rollback="batch_undo_snapshot_restore",
                )
            else:
                apply_and_log(
                    tx_log,
                    op="batch_concept_write_new",
                    target=str(dest),
                    apply_fn=_do_write,
                    rollback="delete",
                )

        if plan.author_writes:
            autores_dir = vault_root / "autores"
            if autores_dir.is_symlink():
                raise ValueError(
                    "vault autores/ must not be a symlink — refusing "
                    "author_writes to avoid escape via symlink target"
                )
        autores_root = (vault_root / "autores").resolve()
        for aw in plan.author_writes:
            dest = _safe_in_vault(vault_root, aw["path"])
            if not dest.is_relative_to(autores_root):
                raise ValueError(
                    f"author_write must target a path under autores/, "
                    f"got {aw['path']!r}"
                )
            dest.parent.mkdir(parents=True, exist_ok=True)
            content = aw["content"]

            def _do_write(dest=dest, content=content) -> None:
                dest.write_text(content, encoding="utf-8")

            if dest.exists():
                snap = _new_backup_path(run_dir, dest.stem)
                shutil.copy2(dest, snap)
                apply_and_log(
                    tx_log,
                    op="batch_author_write_overwrite",
                    target=f"{dest}{_NUL}{snap}",
                    apply_fn=_do_write,
                    rollback="batch_undo_snapshot_restore",
                )
            else:
                apply_and_log(
                    tx_log,
                    op="batch_author_write_new",
                    target=str(dest),
                    apply_fn=_do_write,
                    rollback="delete",
                )

        if plan.tag_index_updates:
            tag_index = vault_root / "_meta" / "_tags.md"
            tag_index.parent.mkdir(parents=True, exist_ok=True)
            tag_snap = _new_backup_path(run_dir, "tags")
            if tag_index.exists():
                shutil.copy2(tag_index, tag_snap)
            else:
                tag_snap.write_text("", encoding="utf-8")
            tag_target = f"{tag_index}{_NUL}{tag_snap}"
            for tu in plan.tag_index_updates:
                for note in tu["notes"]:
                    apply_and_log(
                        tx_log,
                        op="batch_tag_index_update",
                        target=tag_target,
                        apply_fn=lambda tag=tu["tag"], note=note: update_tag_index(
                            tag_index, tag=tag, note_slug=note,
                        ),
                        rollback="batch_undo_snapshot_restore",
                    )

        if plan.log_entries:
            log_path = vault_root / "_meta" / "_processing-log.md"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_snap = _new_backup_path(run_dir, "log")
            existed = "1" if log_path.exists() else "0"
            if log_path.exists():
                shutil.copy2(log_path, log_snap)
            log_target = f"{log_path}{_NUL}{log_snap}{_NUL}{existed}"
            for entry in plan.log_entries:
                apply_and_log(
                    tx_log,
                    op="batch_log_append",
                    target=log_target,
                    apply_fn=lambda entry=entry: append_to_log(log_path, message=entry),
                    rollback="batch_undo_log_append",
                )
    except Exception:
        tx_log.rollback()
        raise
