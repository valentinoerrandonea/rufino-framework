from dataclasses import dataclass, field
from pathlib import Path

import yaml

from rufino.engine.memory_loop.installer import (
    InstallationError,
    install_memory_loop,
)
from rufino.runtime.transaction_log import TransactionLog, apply_and_log
from rufino.wizard.spec_schema import WizardSpec


@dataclass
class MaterializationResult:
    success: bool
    vault_path: Path
    errors: list[str] = field(default_factory=list)


def _kebab(name: str) -> str:
    return name.replace("_", "-").lower()


def materialize(
    *,
    spec: WizardSpec,
    vault_root: Path,
    claude_home: Path,
    state_dir: Path,
) -> MaterializationResult:
    """Big bang: create vault skeleton + install Memory loop adapter transactionally.

    Every disk-touching op is recorded in a TransactionLog and rolled back on
    failure. v1 wires only the Memory loop installer; Ingest/Process/Output
    installers are invoked separately via the per-primitive CLIs until they're
    folded into this orchestrator in a follow-up iteration.
    """
    errors: list[str] = []

    missing_vocab = [e for e in spec.entities if e not in spec.vocabulary]
    if missing_vocab:
        errors.append(f"Entities without vocabulary entry: {missing_vocab}")
        return MaterializationResult(success=False, vault_path=vault_root, errors=errors)

    tx_log: TransactionLog | None = None

    try:
        state_dir_existed_before = state_dir.exists()
        state_dir.mkdir(parents=True, exist_ok=True)
        tx_log = TransactionLog(state_dir / f"materialize-{spec.vertical_name}.json")
        if not state_dir_existed_before:
            apply_and_log(
                tx_log,
                op="mkdir",
                target=str(state_dir),
                apply_fn=lambda: None,  # dir already exists; record for rollback
                rollback="rmdir_if_empty",
            )

        apply_and_log(
            tx_log, op="mkdir", target=str(vault_root),
            apply_fn=lambda: vault_root.mkdir(parents=True),
            rollback="rmdir",
        )
        questions_dir = vault_root / "questions"
        apply_and_log(
            tx_log, op="mkdir", target=str(questions_dir),
            apply_fn=lambda: questions_dir.mkdir(),
            rollback="rmdir",
        )
        inbox_dir = vault_root / "inbox"
        apply_and_log(
            tx_log, op="mkdir", target=str(inbox_dir),
            apply_fn=lambda: inbox_dir.mkdir(),
            rollback="rmdir",
        )
        meta_dir = vault_root / "_meta"
        apply_and_log(
            tx_log, op="mkdir", target=str(meta_dir),
            apply_fn=lambda: meta_dir.mkdir(),
            rollback="rmdir",
        )
        tags_md = meta_dir / "_tags.md"
        apply_and_log(
            tx_log, op="write", target=str(tags_md),
            apply_fn=lambda: tags_md.write_text("# Tags\n", encoding="utf-8"),
            rollback="delete",
        )
        proc_log_md = meta_dir / "_processing-log.md"
        apply_and_log(
            tx_log, op="write", target=str(proc_log_md),
            apply_fn=lambda: proc_log_md.write_text("# Processing log\n", encoding="utf-8"),
            rollback="delete",
        )
        perfil = vault_root / "perfil.md"
        perfil_content = (
            f"---\ntags: [tipo/perfil, vertical/{spec.vertical_name}]\n---\n"
            f"# Perfil ({spec.vertical_name})\n\n(completá con tu info)\n"
        )
        apply_and_log(
            tx_log, op="write", target=str(perfil),
            apply_fn=lambda: perfil.write_text(perfil_content, encoding="utf-8"),
            rollback="delete",
        )

        adapter_dir = state_dir.parent / "adapters" / "memory_loop" / spec.vertical_name
        apply_and_log(
            tx_log, op="mkdir", target=str(adapter_dir),
            apply_fn=lambda: adapter_dir.mkdir(parents=True),
            rollback="rmdir",
        )
        manifest = {
            "adapter_name": f"memory-loop-{_kebab(spec.vertical_name)}",
            "vertical_name": spec.vertical_name,
            "entity_types": list(spec.entities),
            "note_destinations": dict(spec.vocabulary),
            "rule_extensions": [],
        }
        manifest_path = adapter_dir / "manifest.yaml"
        manifest_text = yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True)
        apply_and_log(
            tx_log, op="write", target=str(manifest_path),
            apply_fn=lambda: manifest_path.write_text(manifest_text, encoding="utf-8"),
            rollback="delete",
        )

        try:
            install_memory_loop(
                adapter_dir=adapter_dir,
                claude_home=claude_home,
                vault_path=vault_root,
                log=tx_log,
            )
        except InstallationError as e:
            raise RuntimeError(f"Memory loop install failed: {e}") from e

        from rufino.wizard.post_bootstrap_docs import render_user_readme
        readme = vault_root / "README.md"
        readme_content = render_user_readme(spec)
        apply_and_log(
            tx_log, op="write", target=str(readme),
            apply_fn=lambda: readme.write_text(readme_content, encoding="utf-8"),
            rollback="delete",
        )

    except Exception as e:
        errors.append(f"Materialization failed: {e}")
        if tx_log is not None:
            try:
                tx_log.rollback()
                # Clean the now-empty log file so rmdir_if_empty handlers
                # registered for parent dirs (e.g. state_dir) can succeed.
                log_path = state_dir / f"materialize-{spec.vertical_name}.json"
                if log_path.exists():
                    log_path.unlink()
                if not state_dir_existed_before and state_dir.exists() and not any(state_dir.iterdir()):
                    state_dir.rmdir()
            except Exception as rb_err:
                errors.append(f"Rollback also failed: {rb_err}")
        return MaterializationResult(success=False, vault_path=vault_root, errors=errors)

    return MaterializationResult(success=True, vault_path=vault_root, errors=errors)
