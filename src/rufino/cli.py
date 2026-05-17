from pathlib import Path

import click

from rufino.version import VERSION
from rufino.engine.memory_loop.installer import install_memory_loop, InstallationError
from rufino.engine.process.dispatcher import process_note as _process_note
from rufino.engine.ingest.runner import run_ingest
from rufino.engine.output.dispatcher import dispatch_output
from rufino.engine.output.channels.file_channel import FileChannel
from rufino.engine.process.context_injectors import StubQueryLayer
from rufino.engine.qa.worker import poll_and_dispatch
from rufino.engine.query.api import QueryLayer
from rufino.mcp_server.server import build_server
from rufino.runtime.transaction_log import TransactionLog


class _NoopEmbeddings:
    """Placeholder embedder for v1. Real Ollama wiring lands in plan 9 installer."""

    def embed(self, text: str) -> list[float]:
        return [0.0] * 8


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


@cli.command(name="qa-poll")
@click.option("--vault", "vault_root", required=True, type=click.Path(path_type=Path))
@click.option("--state-dir", "state_dir", required=True, type=click.Path(path_type=Path))
def qa_poll_cmd(vault_root: Path, state_dir: Path) -> None:
    """Poll questions/ for answered questions and dispatch their callbacks.

    In v1, the handler is a no-op placeholder. Real Process adapter resumption
    lands in plan 8 (Wizard wires QALoopAPI into the Process dispatcher).
    """
    def _noop_handler(*, adapter_name, adapter_state, answer):
        click.echo(f"would resume {adapter_name} with answer={answer!r}")

    dispatched = poll_and_dispatch(
        vault_root=vault_root,
        state_dir=state_dir,
        handler=_noop_handler,
    )
    click.echo(f"dispatched={dispatched}")


@cli.command(name="query")
@click.argument("query_string")
@click.option("--vault", "vault_root", required=True,
              type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--mode", default="hybrid", type=click.Choice(["lexical", "semantic", "hybrid"]))
def query_cmd(query_string: str, vault_root: Path, mode: str) -> None:
    """Search the vault."""
    ql = QueryLayer(vault_root=vault_root, embedder=_NoopEmbeddings())
    if mode != "lexical":
        ql.rebuild_indices()
    results = ql.search(query_string, mode=mode)
    for r in results:
        click.echo(r.relative_path)


@cli.command(name="mcp-server")
@click.option("--vault", "vault_root", required=True,
              type=click.Path(exists=True, file_okay=False, path_type=Path))
def mcp_server_cmd(vault_root: Path) -> None:
    """Run the ask-rufino MCP server on stdio."""
    import asyncio
    from mcp.server.stdio import stdio_server

    ql = QueryLayer(vault_root=vault_root, embedder=_NoopEmbeddings())
    server = build_server(ql)

    async def _main() -> None:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    asyncio.run(_main())
