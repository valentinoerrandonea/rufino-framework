import asyncio
import json
from pathlib import Path

import click

from rufino.version import VERSION
from rufino.engine.memory_loop.installer import install_memory_loop, InstallationError
from rufino.engine.process.batch.errors import BatchError, WorkerSessionExpiredError
from rufino.engine.process.batch.runner import run_batch
from rufino.engine.process.dispatcher import process_note as _process_note
from rufino.engine.ingest.runner import run_ingest
from rufino.engine.output.dispatcher import dispatch_output
from rufino.engine.output.channels.file_channel import FileChannel
from rufino.engine.query.api import QueryLayer
from rufino.mcp_server.server import build_server
from rufino.runtime.embedder.resolve import NoopEmbedder, resolve_embedder, write_vault_state
from rufino.runtime.transaction_log import TransactionLog
from rufino.runtime.vault_slug import compute_vault_slug
from rufino.wizard.materializer import materialize
from rufino.wizard.spec_schema import SpecError, validate_spec
from rufino.wizard.system_prompt_assembler import build_system_prompt


DEFAULT_STATE_DIR = Path.home() / ".rufino" / "state"


def _resolve_for_vault(vault_root: Path, state_dir: Path):
    """Resolve the embedder configured for `vault_root` from per-vault state."""
    return resolve_embedder(
        vault_slug=compute_vault_slug(vault_root), state_dir=state_dir,
    )


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
    from rufino.runtime.vault_slug import compute_vault_slug
    # Tx log path must be per-vault, not per-adapter-dir, so two distinct
    # vaults installing from the same adapter dir don't share an audit log
    # (a rollback would then destroy the unrelated install's records).
    tx_path = claude_home / "tx" / f"install-memory-loop-{compute_vault_slug(vault_path)}.json"
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


class _LexicalQueryAdapter:
    """Adapter that exposes a `run(query_string)` method backed by the real
    lexical query layer. Used by `rufino output`: output adapters today only
    consume lexical queries, so the embedder is irrelevant — we pass whatever
    `resolve_embedder` returns to keep the QueryLayer happy."""

    def __init__(self, vault_root: Path, state_dir: Path) -> None:
        self._ql = QueryLayer(
            vault_root=vault_root,
            embedder=_resolve_for_vault(vault_root, state_dir),
        )

    def run(self, query_string: str) -> list[str]:
        return [r.relative_path for r in self._ql.search(query_string, mode="lexical")]


@cli.command(name="output")
@click.argument("adapter_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--vault", "vault_root", required=True, type=click.Path(path_type=Path))
@click.option("--state-dir", "state_dir", default=None,
              type=click.Path(path_type=Path),
              help="Rufino state directory (default: ~/.rufino/state)")
def output_cmd(adapter_dir: Path, vault_root: Path, state_dir: Path | None) -> None:
    """Run an Output adapter once."""
    state_dir = state_dir or DEFAULT_STATE_DIR
    channels = {"file": FileChannel(vault_root=vault_root)}
    result = dispatch_output(
        adapter_dir=adapter_dir,
        query=_LexicalQueryAdapter(vault_root, state_dir),
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
    """Poll questions/ for answered questions and resume their workers."""
    import asyncio
    from rufino.engine.process.batch.errors import WorkerSessionExpiredError
    from rufino.engine.process.batch.qa_resume import resume_pending_qa

    questions_dir = vault_root / "questions"
    if not questions_dir.exists():
        click.echo("dispatched=0")
        return

    answered: list[Path] = []
    for qf in sorted(questions_dir.glob("*.md")):
        text = qf.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("answer:") and stripped not in ("answer:", "answer: "):
                answered.append(qf)
                break

    dispatched = 0
    failures: list[str] = []

    async def _process_all():
        nonlocal dispatched
        for qf in answered:
            try:
                ok = await resume_pending_qa(vault_root=vault_root, question_file=qf)
            except WorkerSessionExpiredError as e:
                failures.append(str(e))
                continue
            if ok:
                dispatched += 1

    asyncio.run(_process_all())
    click.echo(f"dispatched={dispatched}")
    if failures:
        for f in failures:
            click.echo(f"Error: {f}", err=True)
        raise click.exceptions.Exit(code=1)


@cli.command(name="query")
@click.argument("query_string")
@click.option("--vault", "vault_root", required=True,
              type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--mode", default="hybrid", type=click.Choice(["lexical", "semantic", "hybrid"]))
@click.option("--state-dir", "state_dir", default=None,
              type=click.Path(path_type=Path),
              help="Rufino state directory (default: ~/.rufino/state)")
def query_cmd(query_string: str, vault_root: Path, mode: str,
              state_dir: Path | None) -> None:
    """Search the vault."""
    state_dir = state_dir or DEFAULT_STATE_DIR
    embedder = _resolve_for_vault(vault_root, state_dir)
    if mode in ("semantic", "hybrid") and isinstance(embedder, NoopEmbedder):
        click.echo(
            f"Error: --mode={mode} requires embeddings; "
            f"corré `rufino enable-embeddings --vault {vault_root}` y reintentá.",
            err=True,
        )
        raise click.exceptions.Exit(code=2)
    ql = QueryLayer(vault_root=vault_root, embedder=embedder)
    results = ql.search(query_string, mode=mode)
    for r in results:
        click.echo(r.relative_path)


@cli.command(name="mcp-server")
@click.option("--vault", "vault_root", required=True,
              type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--rebuild/--no-rebuild", default=True,
              help="Rebuild semantic+graph indices on startup (default: enabled)")
@click.option("--state-dir", "state_dir", default=None,
              type=click.Path(path_type=Path),
              help="Rufino state directory (default: ~/.rufino/state)")
def mcp_server_cmd(vault_root: Path, rebuild: bool, state_dir: Path | None) -> None:
    """Run the ask-rufino MCP server on stdio."""
    import asyncio
    from mcp.server.stdio import stdio_server

    state_dir = state_dir or DEFAULT_STATE_DIR
    embedder = _resolve_for_vault(vault_root, state_dir)
    ql = QueryLayer(vault_root=vault_root, embedder=embedder)
    if rebuild:
        ql.rebuild_indices()
    server = build_server(ql)

    async def _main() -> None:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    asyncio.run(_main())


@cli.command(name="detect-embeddings")
def detect_embeddings_cmd() -> None:
    """Probe the local Ollama install for an embedding-ready setup."""
    from rufino.runtime.embedder.detect import detect_ollama
    r = detect_ollama()
    if r.binary_present and r.server_running and r.model_installed:
        click.echo("OK: ollama + nomic-embed-text ready")
        return
    click.echo(f"NOT READY: {r.error}", err=True)
    raise click.exceptions.Exit(code=1)


@cli.command(name="enable-embeddings")
@click.option("--vault", "vault_root", required=True, type=click.Path(path_type=Path),
              help="Vault root path")
@click.option("--state-dir", "state_dir", required=True, type=click.Path(path_type=Path),
              help="Rufino state directory (typically ~/.rufino/state)")
@click.option("--model", default="nomic-embed-text",
              help="Ollama embedding model (default: nomic-embed-text)")
def enable_embeddings_cmd(vault_root: Path, state_dir: Path, model: str) -> None:
    """Enable semantic embeddings for a vault. Requires ollama + nomic-embed-text."""
    from rufino.runtime.embedder.detect import detect_ollama
    from rufino.runtime.embedder.ollama import OllamaEmbedder

    r = detect_ollama(model=model)
    if not (r.binary_present and r.server_running and r.model_installed):
        click.echo(f"Error: {r.error}", err=True)
        raise click.exceptions.Exit(code=1)

    vault_root = vault_root.expanduser().resolve()
    state_dir = state_dir.expanduser().resolve()
    slug = compute_vault_slug(vault_root)
    # Build the index BEFORE marking embeddings enabled in state. If
    # rebuild_indices crashes (Ollama mid-request, disk full, model
    # uninstalled between detect and embed), the per-vault state stays in
    # its prior value — semantic queries continue to NoopEmbedder instead
    # of pointing at a half-built index.
    ql = QueryLayer(vault_root=vault_root, embedder=OllamaEmbedder(model=model))
    ql.rebuild_indices()
    write_vault_state(
        vault_slug=slug, state_dir=state_dir,
        embeddings_enabled=True, backend="ollama", model=model,
    )
    click.echo(f"Embeddings enabled for {slug} (model={model})")


@cli.command(name="disable-embeddings")
@click.option("--vault", "vault_root", required=True, type=click.Path(path_type=Path))
@click.option("--state-dir", "state_dir", required=True, type=click.Path(path_type=Path))
def disable_embeddings_cmd(vault_root: Path, state_dir: Path) -> None:
    """Disable semantic embeddings for a vault. Idempotent; preserves indices."""
    vault_root = vault_root.expanduser().resolve()
    state_dir = state_dir.expanduser().resolve()
    slug = compute_vault_slug(vault_root)
    write_vault_state(vault_slug=slug, state_dir=state_dir, embeddings_enabled=False)
    click.echo(f"Embeddings disabled for {slug}")


@cli.command(name="bootstrap")
@click.option("--dry-run", is_flag=True,
              help="Print system prompt to stdout instead of launching claude")
def bootstrap_cmd(dry_run: bool) -> None:
    """Start the conversational wizard."""
    system_prompt = build_system_prompt()
    if dry_run:
        click.echo(system_prompt)
        return
    import shutil
    import subprocess
    if shutil.which("claude") is None:
        click.echo(
            "Error: 'claude' CLI no encontrado en PATH. "
            "Instalalo y volvé a correr `rufino bootstrap`.",
            err=True,
        )
        raise click.exceptions.Exit(code=127)
    # Interactive session with the wizard system prompt. NOT `-p/--print` —
    # that is headless one-shot mode (Claude reads the prompt as a user
    # message, replies once, exits). The wizard needs back-and-forth, so
    # we use the default interactive mode and inject our prompt via
    # `--system-prompt`.
    #
    # The trailing positional arg is the *initial user message* — without it
    # Claude Code opens silently and waits for the user to type first.
    # Passing a kickoff message makes the wizard greet and ask its first
    # question, which is what the user expects from `rufino bootstrap`.
    proc = subprocess.run(
        [
            "claude",
            "--system-prompt", system_prompt,
            "--allowedTools",
            (
                "Bash(rufino materialize:*),"
                "Bash(rufino query:*),"
                "Bash(rufino process-batch:*),"
                "Bash(rufino detect-embeddings:*),"
                "Bash(rufino enable-embeddings:*),"
                "Bash(rufino install-ingest:*),"
                "Read,Write"
            ),
            "--",  # end-of-options marker so --allowedTools doesn't slurp the prompt
            "Saludá y arrancá la entrevista del wizard.",
        ],
        check=False,
    )
    if proc.returncode != 0:
        raise click.exceptions.Exit(code=proc.returncode)


@cli.command(name="materialize")
@click.option("--spec", "spec_path", required=True,
              type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--vault", "vault_root", required=True, type=click.Path(path_type=Path))
@click.option("--claude-home", "claude_home", required=True, type=click.Path(path_type=Path))
@click.option("--state-dir", "state_dir", required=True, type=click.Path(path_type=Path))
@click.option("--install-hooks/--no-install-hooks", default=False,
              help="Install Claude Code hooks that capture conversations into "
                   "this vault. Opt-in (default: off).")
@click.option("--embeddings/--no-embeddings", default=False,
              help="Enable semantic embeddings on materialize. Requires ollama "
                   "+ nomic-embed-text. Default: off (lexical-only).")
def materialize_cmd(
    spec_path: Path, vault_root: Path, claude_home: Path, state_dir: Path,
    install_hooks: bool, embeddings: bool,
) -> None:
    """Materialize the system described in a WizardSpec JSON file."""
    raw = json.loads(spec_path.read_text(encoding="utf-8"))
    try:
        spec = validate_spec(raw)
    except SpecError as e:
        click.echo(f"Spec validation failed: {e}", err=True)
        raise click.exceptions.Exit(code=1)

    state_dir_resolved = state_dir.expanduser().resolve()
    result = materialize(
        spec=spec,
        vault_root=vault_root.expanduser().resolve(),
        claude_home=claude_home.expanduser().resolve(),
        state_dir=state_dir_resolved,
        install_hooks=install_hooks,
    )

    if not result.success:
        for err in result.errors:
            click.echo(f"ERROR: {err}", err=True)
        raise click.exceptions.Exit(code=2)

    # Record the embeddings choice in per-vault state so subsequent
    # `rufino query` / `mcp-server` calls resolve the right embedder
    # without re-prompting the user.
    write_vault_state(
        vault_slug=compute_vault_slug(result.vault_path),
        state_dir=state_dir_resolved,
        embeddings_enabled=embeddings,
    )

    # Register a per-vault MCP server in ~/.claude.json so Claude Code can
    # query the freshly materialized vault without clobbering other vaults'
    # entries. Uses sys.argv[0] (the rufino CLI that's currently running) so
    # the command stays correct under pipx/venv.
    import sys
    from rufino.runtime.claude_config import register_mcp_server
    server_name = f"ask-rufino-{compute_vault_slug(result.vault_path)}"
    claude_config = Path.home() / ".claude.json"
    register_mcp_server(
        claude_config_path=claude_config,
        server_name=server_name,
        command=sys.argv[0] if sys.argv and sys.argv[0] else "rufino",
        # Pass --state-dir explicitly so the MCP server reads embedding
        # state from the same dir we just wrote to — otherwise a custom
        # --state-dir at materialize time would silently fall back to the
        # default and `--mode=hybrid` would degrade to NoopEmbedder.
        args=[
            "mcp-server", "--vault", str(result.vault_path),
            "--state-dir", str(state_dir_resolved),
        ],
    )
    click.echo(f"Vault materialized at {result.vault_path}")
    click.echo(f"Registered {server_name} MCP at {claude_config}")


@cli.command(name="process-batch")
@click.argument("source", type=click.Path(exists=True, path_type=Path))
@click.option("--adapter", "adapter_dir", required=True,
              type=click.Path(exists=True, file_okay=False, path_type=Path),
              help="Path to the Process adapter directory")
@click.option("--vault", "vault_root", required=True,
              type=click.Path(path_type=Path),
              help="Vault root")
@click.option("--workers", type=int, default=None,
              help="Max concurrent workers (default: min(4, num_groups))")
@click.option("--batch-size", "batch_size", type=int, default=None,
              help="Override the adapter manifest's batch_size")
@click.option("--dry-run", is_flag=True,
              help="Stop after PLAN; print the plan path; do not spawn workers")
def process_batch_cmd(
    source: Path, adapter_dir: Path, vault_root: Path,
    workers: int | None, batch_size: int | None, dry_run: bool,
) -> None:
    """Process a corpus (ZIP or directory) into augmented vault notes."""
    try:
        result = asyncio.run(run_batch(
            source=source, adapter_dir=adapter_dir, vault_root=vault_root,
            workers=workers, batch_size=batch_size, dry_run=dry_run,
        ))
    except WorkerSessionExpiredError as e:
        click.echo(f"Error: {e}", err=True)
        raise click.exceptions.Exit(code=1)
    except BatchError as e:
        click.echo(f"Error: {e}", err=True)
        raise click.exceptions.Exit(code=1)
    except FileNotFoundError as e:
        if getattr(e, "filename", None) == "claude":
            click.echo("Error: `claude` no encontrado en PATH.", err=True)
            raise click.exceptions.Exit(code=127)
        raise

    if result.dry_run:
        click.echo(f"dry-run: plan written to {result.plan_path}")
        click.echo(f"notes_total={result.notes_total}")
        return
    click.echo(
        f"run_id={result.run_id} total={result.notes_total} "
        f"ok={result.notes_ok} failed={result.notes_failed} "
        f"pending_qa={result.notes_pending_qa}"
    )
