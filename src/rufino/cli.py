from pathlib import Path

import click

from rufino.version import VERSION
from rufino.engine.memory_loop.installer import install_memory_loop, InstallationError
from rufino.runtime.transaction_log import TransactionLog


@click.group()
def cli() -> None:
    """Rufino Framework CLI."""


@cli.command()
def version() -> None:
    """Print framework version."""
    click.echo(VERSION)


@cli.command(name="install-memory-loop")
@click.argument("adapter_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--vault", "vault_path", required=True, type=click.Path(path_type=Path),
              help="Path to the user's vault root")
@click.option("--claude-home", "claude_home", required=True, type=click.Path(path_type=Path),
              help="Path to user's ~/.claude/ directory")
def install_memory_loop_cmd(adapter_dir: Path, vault_path: Path, claude_home: Path) -> None:
    """Install a Memory loop adapter into ~/.claude/."""
    tx_path = claude_home / "tx" / f"install-memory-loop-{adapter_dir.name}.json"
    tx_path.parent.mkdir(parents=True, exist_ok=True)
    tx_log = TransactionLog(tx_path)
    try:
        install_memory_loop(
            adapter_dir=adapter_dir,
            claude_home=claude_home,
            vault_path=vault_path,
            log=tx_log,
        )
    except InstallationError as e:
        click.echo(f"Error: {e}", err=True)
        raise click.exceptions.Exit(code=1)
    click.echo(f"Adapter '{adapter_dir.name}' installed to {claude_home}")
