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

    v1 wires only the Memory loop installer; Ingest/Process/Output installers
    are invoked separately via the per-primitive CLIs until they're folded into
    this orchestrator in a follow-up iteration.
    """
    errors: list[str] = []

    missing_vocab = [e for e in spec.entities if e not in spec.vocabulary]
    if missing_vocab:
        errors.append(
            f"Entities without vocabulary entry: {missing_vocab}"
        )
        return MaterializationResult(success=False, vault_path=vault_root, errors=errors)

    state_dir.mkdir(parents=True, exist_ok=True)
    tx_log = TransactionLog(state_dir / f"materialize-{spec.vertical_name}.json")

    try:
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
        adapter_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "adapter_name": f"memory-loop-{_kebab(spec.vertical_name)}",
            "vertical_name": spec.vertical_name,
            "entity_types": list(spec.entities),
            "note_destinations": dict(spec.vocabulary),
            "rule_extensions": [],
        }
        (adapter_dir / "manifest.yaml").write_text(
            yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
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
        tx_log.rollback()
        return MaterializationResult(success=False, vault_path=vault_root, errors=errors)

    return MaterializationResult(success=True, vault_path=vault_root, errors=errors)
