"""Apply a ConsolidationPlan to the vault via the transaction log."""
import shutil
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


def _safe_in_vault(vault_root: Path, rel: str) -> Path:
    target = (vault_root / rel).resolve()
    root = vault_root.resolve()
    if not target.is_relative_to(root):
        raise ValueError(f"path escapes vault: {rel!r}")
    return target


def _undo_move(target: str) -> None:
    if "\x00" not in target:
        return
    dest, src = target.split("\x00", 1)
    if Path(dest).exists():
        Path(src).parent.mkdir(parents=True, exist_ok=True)
        shutil.move(dest, src)


def _undo_concept_overwrite(target: str) -> None:
    if "\x00" not in target:
        return
    dest, backup = target.split("\x00", 1)
    if Path(backup).exists():
        shutil.copy2(backup, dest)
        Path(backup).unlink()


register_rollback("batch_undo_move", _undo_move)
register_rollback("batch_undo_concept_overwrite", _undo_concept_overwrite)


def commit(
    *,
    plan: ConsolidationPlan,
    vault_root: Path,
    run_dir: Path,
    tx_log: TransactionLog,
) -> None:
    """Apply plan via tx_log. On any failure, rollback restores state and the
    exception propagates."""
    try:
        for m in plan.moves:
            src = (run_dir / m["from"]).resolve()
            dest = _safe_in_vault(vault_root, m["to"])
            if not src.exists():
                raise FileNotFoundError(f"missing source: {src}")
            dest.parent.mkdir(parents=True, exist_ok=True)

            def _do_move(src=src, dest=dest):
                shutil.move(str(src), str(dest))

            apply_and_log(
                tx_log,
                op="batch_move",
                target=f"{dest}\x00{src}",
                apply_fn=_do_move,
                rollback="batch_undo_move",
            )

        for cw in plan.concept_writes:
            dest = _safe_in_vault(vault_root, cw["path"])
            dest.parent.mkdir(parents=True, exist_ok=True)
            existed = dest.exists()
            previous = dest.read_text(encoding="utf-8") if existed else None

            def _do_write(dest=dest, content=cw["content"]):
                dest.write_text(content, encoding="utf-8")

            if existed:
                backup = dest.with_suffix(dest.suffix + ".pre-batch")
                backup.write_text(previous, encoding="utf-8")
                apply_and_log(
                    tx_log,
                    op="batch_concept_write_overwrite",
                    target=f"{dest}\x00{backup}",
                    apply_fn=_do_write,
                    rollback="batch_undo_concept_overwrite",
                )
            else:
                apply_and_log(
                    tx_log,
                    op="batch_concept_write_new",
                    target=str(dest),
                    apply_fn=_do_write,
                    rollback="delete",
                )

        if plan.tag_index_updates:
            tag_index = vault_root / "_meta" / "_tags.md"
            snap = tag_index.with_suffix(tag_index.suffix + ".pre-batch")
            if tag_index.exists():
                shutil.copy2(tag_index, snap)
            else:
                snap.write_text("", encoding="utf-8")

            def _restore_tags(target=str(tag_index), backup=str(snap)):
                shutil.copy2(backup, target)

            register_rollback("batch_undo_tag_index", _restore_tags)
            for tu in plan.tag_index_updates:
                for note in tu["notes"]:
                    apply_and_log(
                        tx_log,
                        op="batch_tag_index_update",
                        target=f"{tag_index}\x00{snap}",
                        apply_fn=lambda tag=tu["tag"], note=note: update_tag_index(
                            tag_index, tag=tag, note_slug=note,
                        ),
                        rollback="batch_undo_tag_index",
                    )

        log_path = vault_root / "_meta" / "_processing-log.md"
        for entry in plan.log_entries:
            apply_and_log(
                tx_log,
                op="batch_log_append",
                target=str(log_path),
                apply_fn=lambda entry=entry: append_to_log(log_path, message=entry),
                rollback="rmdir_if_empty",
            )
    except Exception:
        tx_log.rollback()
        raise
