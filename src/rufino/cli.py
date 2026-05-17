from pathlib import Path

import click

from rufino.version import VERSION
from rufino.engine.memory_loop.installer import install_memory_loop, InstallationError
from rufino.engine.process.dispatcher import process_note as _process_note
from rufino.engine.ingest.runner import run_ingest
from rufino.engine.output.dispatcher import dispatch_output
from rufino.engine.output.channels.file_channel import FileChannel
from rufino.engine.process.context_injectors import StubQueryLayer
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
        tx_log.rollback()
        click.echo(f"Error: {e}", err=True)
        raise click.exceptions.Exit(code=1)
    click.echo(f"Adapter '{adapter_dir.name}' installed to {claude_home}")


@cli.command(name="process")
@click.argument("note_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--vault", "vault_root", required=True, type=click.Path(path_type=Path),
              help="Vault root path")
@click.option("--mode", default="light", type=click.Choice(["light", "full", "lint"]))
@click.option("--adapter-dir", type=click.Path(path_type=Path),
              help="Required for --mode full")
def process_cmd(note_path: Path, vault_root: Path, mode: str, adapter_dir: Path | None) -> None:
    """Process a single note. v1 supports light mode without an adapter."""
    if mode == "full" and adapter_dir is None:
        click.echo("Error: --adapter-dir required for --mode full", err=True)
        raise click.exceptions.Exit(code=1)
    if mode == "full":
        click.echo("Error: full mode CLI wiring lands in plan 7 (needs real LLM + Query)", err=True)
        raise click.exceptions.Exit(code=2)
    result = _process_note(note_path=note_path, vault_root=vault_root, mode=mode)
    click.echo(f"{result.message}")


@cli.command(name="ingest")
@click.argument("adapter_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--vault", "vault_root", required=True, type=click.Path(path_type=Path))
@click.option("--state-dir", "state_dir", required=True, type=click.Path(path_type=Path))
def ingest_cmd(adapter_dir: Path, vault_root: Path, state_dir: Path) -> None:
    """Run an Ingest adapter once."""
    result = run_ingest(
        adapter_dir=adapter_dir,
        vault_root=vault_root,
        rufino_state_dir=state_dir,
    )
    click.echo(
        f"adapter={result.adapter_name} emitted={result.facts_emitted} "
        f"skipped={result.facts_skipped} errors={len(result.errors)}"
    )
    for err in result.errors:
        click.echo(f"  error: {err}", err=True)


@cli.command(name="output")
@click.argument("adapter_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--vault", "vault_root", required=True, type=click.Path(path_type=Path))
def output_cmd(adapter_dir: Path, vault_root: Path) -> None:
    """Run an Output adapter once (uses stub Query layer in v1)."""
    channels = {"file": FileChannel(vault_root=vault_root)}
    result = dispatch_output(
        adapter_dir=adapter_dir,
        query=StubQueryLayer(),
        channels=channels,
        event_context={},
    )
    click.echo(
        f"adapter={result.adapter_name} deliveries={result.deliveries} "
        f"errors={len(result.errors)}"
    )
