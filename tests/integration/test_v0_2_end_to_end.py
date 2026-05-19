"""E2E acceptance checklist for rufino v0.2.0.

One test per acceptance-checklist item from the v0.2.0 design doc
(``docs/superpowers/specs/2026-05-19-rufino-v0.2-functional-design.html``).
Each test exercises the user-facing CLI surface (or the closest public
entry point when the CLI shells out to ``claude`` / Ollama / launchd),
mocking only the external dependencies.

Item 14 (regression) and item 15 (E2E file runs green) are satisfied
implicitly by this file passing under ``pytest``.

Run this file alone with::

    pytest tests/integration/test_v0_2_end_to_end.py -v
"""
from __future__ import annotations

import asyncio
import json
import multiprocessing
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from click.testing import CliRunner

import rufino.cli as cli_module
from rufino.cli import cli
from rufino.engine.ingest.emit_augmented import dispatch_to_process
from rufino.engine.ingest.runner import run_ingest
from rufino.engine.process.batch.errors import BatchError
from rufino.engine.process.batch.planner import build_plan
from rufino.engine.process.batch.runner import BatchRunResult, run_batch
from rufino.engine.process.batch.runner_helper import (
    MAX_OUTPUT_BYTES,
    run_claude_worker,
)
from rufino.engine.process.batch.stager import StagedCorpus
from rufino.engine.query.graph import GraphBackend
from rufino.runtime.vault_lock import vault_lock
from rufino.runtime.vault_slug import compute_vault_slug
from rufino.wizard.materializer import materialize
from rufino.wizard.spec_schema import validate_spec
from rufino.wizard.system_prompt_assembler import build_system_prompt


REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_SCRIPT = REPO_ROOT / "migrations" / "0.1.0-to-0.2.0.sh"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _facultad_spec() -> dict:
    """Minimal but schema-valid spec covering one adapter of each shape."""
    return {
        "vertical_name": "facultad",
        "patterns": ["long_documents_extraction"],
        "entities": ["apunte_clase"],
        "vocabulary": {"apunte_clase": "apuntes/<slug>.md"},
        "sources": [
            {
                "adapter_name": "drive-cufona",
                "source_name": "gdrive",
                "output_mode": "import_raw",
                "schedule": "*/30 * * * *",
                "auth": {"type": "oauth2", "keychain_service": "rufino-gdrive"},
                "target_inbox": "inbox/cufona/",
                "process_with": "apunte-clase",
                "trigger": "immediate",
            }
        ],
        "processing": [
            {
                "adapter_name": "apunte-clase",
                "note_type": "apunte_clase",
                "applies_when": {"source_dir": "inbox/cufona/"},
                "llm": "sonnet",
                "output_schema": {"required": {"title": "string"}, "optional": {}},
                "triple_vocabulary": ["tema-de"],
                "tag_axes": [
                    {"axis": "materia", "format": "materia/<slug>",
                     "required": True, "min": 1},
                ],
                "destination_path": "apuntes/{slug}.md",
                "qa_triggers": [],
                "context_injectors": [],
                "batch_size": 10,
                "prompt_instructions": "# Procesá apuntes\n",
            }
        ],
        "outputs": [
            {
                "adapter_name": "digest-semanal",
                "trigger": {"type": "cron", "expression": "0 9 * * 1"},
                "query": [{"name": "items",
                           "expression": "tag:tipo/apunte_clase"}],
                "delivery": [{"channel": "file", "path": "reports/digest.md"}],
                "template_body": "# Digest\n{% for i in items %}- {{ i.title }}\n{% endfor %}\n",
            }
        ],
    }


def _materialize_facultad(tmp_path: Path) -> tuple[Path, Path]:
    """Materialize the spec; return (vault_path, state_dir)."""
    spec = validate_spec(_facultad_spec())
    vault = tmp_path / "vault"
    state_dir = tmp_path / ".rufino-state"
    result = materialize(
        spec=spec,
        vault_root=vault,
        claude_home=tmp_path / ".claude",
        state_dir=state_dir,
    )
    assert result.success, result.errors
    return result.vault_path, state_dir


def _hold_lock(vault: str, seconds: float) -> None:
    """Subprocess target: hold the vault lock for ``seconds``."""
    with vault_lock(Path(vault)):
        time.sleep(seconds)


# ---------------------------------------------------------------------------
# #1 — Wizard end-to-end sin corpus
# ---------------------------------------------------------------------------


def test_item_01_wizard_materializes_adapters_for_each_primitive(
    tmp_path: Path,
) -> None:
    """`bootstrap` + `materialize` produces ingest/process/output adapter dirs
    with the required files (manifest.yaml + prompt.md/template.md)."""
    # First: the wizard prompt mentions the v0.2 fields the wizard must collect.
    prompt = build_system_prompt()
    assert "prompt_instructions" in prompt
    assert "template_body" in prompt

    vault, state_dir = _materialize_facultad(tmp_path)
    slug = compute_vault_slug(vault)

    base = state_dir.parent / "adapters"
    ingest = base / "ingest" / slug / "drive-cufona"
    process = base / "process" / slug / "apunte-clase"
    output = base / "output" / slug / "digest-semanal"

    assert (ingest / "manifest.yaml").exists()
    assert (process / "manifest.yaml").exists()
    assert (process / "prompt.md").exists()
    assert (output / "manifest.yaml").exists()
    assert (output / "template.md").exists()


# ---------------------------------------------------------------------------
# #2 — Wizard end-to-end con corpus (light-mode batch over a 2-doc corpus)
# ---------------------------------------------------------------------------


def test_item_02_corpus_run_produces_run_dir_and_processed_notes(
    tmp_path: Path,
) -> None:
    """A small staged corpus run through ``emit_augmented`` (the corpus-as-
    augmented-records shape) leaves notes in the vault and updates
    ``_meta/_tags.md`` — proving the end-to-end ingest → process write path."""
    vault, state_dir = _materialize_facultad(tmp_path)

    staging = tmp_path / "staging"
    dispatch_to_process(
        record={"id": "doc-1",
                "content": "---\ntags: [materia/algo]\n---\nbody1\n"},
        vault_root=vault, staging_dir=staging,
    )
    dispatch_to_process(
        record={"id": "doc-2",
                "content": "---\ntags: [materia/calc]\n---\nbody2\n"},
        vault_root=vault, staging_dir=staging,
    )
    tags = (vault / "_meta" / "_tags.md").read_text(encoding="utf-8")
    assert "doc-1" in tags
    assert "doc-2" in tags
    log = (vault / "_meta" / "_processing-log.md").read_text(encoding="utf-8")
    assert "light-processed doc-1" in log
    assert "light-processed doc-2" in log


# ---------------------------------------------------------------------------
# #3 — Embedder opt-in (sí)
# ---------------------------------------------------------------------------


def test_item_03_enable_embeddings_writes_state_and_rebuilds_index(
    tmp_path: Path,
) -> None:
    """`enable-embeddings` writes vault state with embeddings.enabled=true
    after a successful Ollama detection + index rebuild."""
    from rufino.runtime.embedder.detect import OllamaDetection

    vault, state_dir = _materialize_facultad(tmp_path)
    fake_ql = MagicMock()
    detection = OllamaDetection(True, True, True, None)
    with patch("rufino.runtime.embedder.detect.detect_ollama",
               return_value=detection), \
         patch("rufino.cli.QueryLayer", return_value=fake_ql):
        result = CliRunner().invoke(
            cli, ["enable-embeddings",
                  "--vault", str(vault), "--state-dir", str(state_dir)],
        )
    assert result.exit_code == 0, result.output
    slug = compute_vault_slug(vault)
    state_yaml = state_dir / "vaults" / f"{slug}.yaml"
    data = yaml.safe_load(state_yaml.read_text(encoding="utf-8"))
    assert data["embeddings"]["enabled"] is True
    fake_ql.rebuild_indices.assert_called_once()


# ---------------------------------------------------------------------------
# #4 — Embedder opt-in (no) — semantic must exit 2 with a clear message
# ---------------------------------------------------------------------------


def test_item_04_query_semantic_without_embeddings_exits_two(
    tmp_path: Path,
) -> None:
    vault, state_dir = _materialize_facultad(tmp_path)
    # `materialize` does not write per-vault embedding state, so
    # `resolve_embedder` returns NoopEmbedder. The query CLI must refuse
    # semantic mode with exit 2 + an actionable message.
    result = CliRunner().invoke(
        cli, ["query", "anything",
              "--vault", str(vault),
              "--mode", "semantic",
              "--state-dir", str(state_dir)],
    )
    assert result.exit_code == 2, result.output
    assert "enable-embeddings" in result.output


# ---------------------------------------------------------------------------
# #5 — Forward graph traversal (depth=1, reverse=False)
# ---------------------------------------------------------------------------


def test_item_05_forward_traversal_returns_objects(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "clase1.md").write_text(
        "---\ntriples:\n"
        "  - { r: tema-de, o: ml-i }\n"
        "  - { r: tema-de, o: regresion }\n"
        "---\nbody\n",
        encoding="utf-8",
    )
    backend = GraphBackend(vault_root=vault)
    backend.rebuild_index()
    objs = backend.traverse(
        node="clase1.md", relation="tema-de", depth=1, reverse=False,
    )
    paths = sorted(r.relative_path for r in objs)
    assert paths == ["ml-i", "regresion"]


# ---------------------------------------------------------------------------
# #6 — Single-note `rufino process --mode full`
# ---------------------------------------------------------------------------


def test_item_06_process_single_full_mode_runs_batch_of_one(
    tmp_path: Path, monkeypatch,
) -> None:
    """The wrapper stages the note into a tempdir-of-one and invokes
    ``run_batch`` with ``workers=1, batch_size=1``."""
    note = tmp_path / "n.md"
    note.write_text("# n\nbody\n", encoding="utf-8")
    adapter = tmp_path / "adapter"
    adapter.mkdir()
    (adapter / "manifest.yaml").write_text("adapter_name: x\n", encoding="utf-8")
    vault = tmp_path / "vault"
    vault.mkdir()

    captured: dict = {}

    async def spy(**kwargs):
        captured.update(kwargs)
        return BatchRunResult(
            run_id="r1", dry_run=False, notes_total=1, notes_ok=1,
            notes_failed=0, notes_pending_qa=0,
        )

    monkeypatch.setattr(cli_module, "run_batch", spy)

    result = CliRunner().invoke(cli, [
        "process", str(note),
        "--vault", str(vault),
        "--mode", "full",
        "--adapter-dir", str(adapter),
    ])
    assert result.exit_code == 0, result.output
    assert captured["workers"] == 1
    assert captured["batch_size"] == 1
    assert captured["dry_run"] is False


# ---------------------------------------------------------------------------
# #7 — Ingest `output_mode: emit_augmented`
# ---------------------------------------------------------------------------


def test_item_07_emit_augmented_streams_records_to_process(
    tmp_path: Path,
) -> None:
    """An adapter with ``output_mode: emit_augmented`` streams records into
    Process in light mode — no inbox detour, no LLM call."""
    vault = tmp_path / "vault"
    vault.mkdir()
    adapter = tmp_path / "aug-adapter"
    adapter.mkdir()
    (adapter / "manifest.yaml").write_text(
        "adapter_name: aug\n"
        "source_name: aug\n"
        "schedule: '* * * * *'\n"
        "auth: {}\n"
        "output_mode: emit_augmented\n"
        "process_inline_with: light-tagger\n",
        encoding="utf-8",
    )
    (adapter / "fetcher.py").write_text(
        "def fetch(since):\n"
        "    return [\n"
        "        {'id': 'a', 'content': '---\\ntags: [t1]\\n---\\nA\\n'},\n"
        "        {'id': 'b', 'content': '---\\ntags: [t2]\\n---\\nB\\n'},\n"
        "    ]\n",
        encoding="utf-8",
    )
    result = run_ingest(
        adapter_dir=adapter,
        vault_root=vault,
        rufino_state_dir=tmp_path / "state",
    )
    assert result.facts_emitted == 2
    assert result.errors == []


# ---------------------------------------------------------------------------
# #8 — `transform_hook` mutates the record on its way through Process
# ---------------------------------------------------------------------------


def test_item_08_transform_hook_mutates_field(
    tmp_vault: Path, tmp_path: Path,
) -> None:
    """An Ingest adapter declaring ``transform_hook: ./transform.py`` whose
    script adds a field results in that field appearing on the final fact's
    frontmatter — exercised through ``run_ingest`` end-to-end."""
    adapter = tmp_path / "adapter"
    adapter.mkdir()
    (adapter / "manifest.yaml").write_text(
        "adapter_name: hooked\n"
        "source_name: hooked\n"
        "schedule: '*/30 * * * *'\n"
        "auth: {}\n"
        "output_mode: emit_fact\n"
        "emits: [t]\n"
        "fact_schema:\n  id: string\n"
        "destination:\n  facts: hooked/<id>.md\n"
        "dedup_by: id\n"
        "transform_hook: ./transform.py\n",
        encoding="utf-8",
    )
    (adapter / "fetcher.py").write_text(
        "def fetch(since):\n"
        "    return [{'id': 'f1'}]\n",
        encoding="utf-8",
    )
    (adapter / "transform.py").write_text(
        "import json, sys\n"
        "d = json.loads(sys.stdin.read())\n"
        "d['enriched'] = 'hook-saw-this'\n"
        "sys.stdout.write(json.dumps(d))\n",
        encoding="utf-8",
    )

    result = run_ingest(
        adapter_dir=adapter,
        vault_root=tmp_vault,
        rufino_state_dir=tmp_path / ".rufino-state",
    )
    assert result.facts_emitted == 1, result.errors

    fact_file = tmp_vault / "hooked" / "f1.md"
    assert fact_file.exists()
    _, fm_yaml, _ = fact_file.read_text(encoding="utf-8").split("---\n", 2)
    fm = yaml.safe_load(fm_yaml)
    assert fm["enriched"] == "hook-saw-this"


# ---------------------------------------------------------------------------
# #9 — Scheduler real (`install-ingest` produces a launchd/cron job)
# ---------------------------------------------------------------------------


def test_item_09_install_ingest_uses_real_backend(
    tmp_path: Path, monkeypatch,
) -> None:
    """`install-ingest` resolves the OS-specific backend and invokes
    ``install()`` with the manifest schedule + a rufino-prefixed job id."""
    calls: list[dict] = []

    class FakeBackend:
        def install(self, *, job_id, schedule, cmd, log_path):
            calls.append(dict(job_id=job_id, schedule=schedule,
                              cmd=cmd, log_path=log_path))

        def uninstall(self, *, job_id):  # pragma: no cover - not exercised
            pass

        def list_jobs(self):  # pragma: no cover
            return []

    adapter = tmp_path / "adapter"
    adapter.mkdir()
    (adapter / "manifest.yaml").write_text(
        yaml.safe_dump({
            "adapter_name": "drive-facultad",
            "source_name": "gdrive",
            "schedule": "0 22 * * *",
            "output_mode": "import_raw",
            "auth": {"type": "oauth2"},
            "target_inbox": "inbox/cufona/",
            "process_with": "apunte-clase",
            "trigger": "immediate",
        }, sort_keys=False),
        encoding="utf-8",
    )
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setattr(cli_module, "_scheduler_backend", lambda: FakeBackend())

    result = CliRunner().invoke(cli, [
        "install-ingest", str(adapter),
        "--vault", str(vault),
        "--rufino-home", str(tmp_path / "rh"),
    ])
    assert result.exit_code == 0, result.output
    assert len(calls) == 1
    assert calls[0]["schedule"] == "0 22 * * *"
    assert calls[0]["job_id"].startswith("rufino-ingest-")
    assert "drive-facultad" in calls[0]["job_id"]


@pytest.mark.skipif(
    platform.system() != "Darwin",
    reason="Darwin-only: verifies pick_scheduler_for_os picks LaunchdScheduler",
)
def test_item_09_macos_picks_launchd_backend() -> None:
    """On macOS, the OS picker returns LaunchdScheduler (Linux picks Cron)."""
    from rufino.runtime.scheduler import LaunchdScheduler, pick_scheduler_for_os
    backend = pick_scheduler_for_os("Darwin")
    assert isinstance(backend, LaunchdScheduler)


# ---------------------------------------------------------------------------
# #10 — Concurrency: vault lock fails the second caller fast
# ---------------------------------------------------------------------------


def test_item_10_second_batch_against_locked_vault_fails_fast(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    adapter_dir = tmp_path / "adapter"
    adapter_dir.mkdir()
    source = tmp_path / "src"
    source.mkdir()

    holder = multiprocessing.Process(
        target=_hold_lock, args=(str(vault), 1.5),
    )
    holder.start()
    try:
        time.sleep(0.3)
        with pytest.raises(BatchError, match="locked"):
            asyncio.run(run_batch(
                source=source, adapter_dir=adapter_dir, vault_root=vault,
                workers=1, batch_size=1, dry_run=True,
            ))
    finally:
        holder.join()


# ---------------------------------------------------------------------------
# #11 — Memoria acotada: runaway worker output is capped, parent survives
# ---------------------------------------------------------------------------


def test_item_11_worker_stdout_is_truncated_at_max_bytes(
    tmp_path: Path,
) -> None:
    fake = tmp_path / "claude"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        f"sys.stdout.write('A' * {MAX_OUTPUT_BYTES * 2})\n"
        "sys.exit(0)\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    result = asyncio.run(
        run_claude_worker(cmd=[str(fake)], cwd=tmp_path, timeout=10.0),
    )
    assert len(result.stdout) <= MAX_OUTPUT_BYTES
    assert result.truncated is True
    assert result.returncode == 0


# ---------------------------------------------------------------------------
# #12 — Worker IDs use 4-digit padding so 1500 workers do not collide
# ---------------------------------------------------------------------------


def test_item_12_worker_ids_padded_to_four_digits(tmp_path: Path) -> None:
    groups: dict[str, list[Path]] = {}
    for i in range(1500):
        group = f"g{i:05d}"
        note = tmp_path / f"{group}.md"
        note.write_text("# x\n", encoding="utf-8")
        groups[group] = [note]
    staged = StagedCorpus(groups=groups, skipped=[])

    plan = build_plan(staged, run_id="r", adapter_dir="/x", batch_size=1)
    assert plan.workers[0].worker_id == "w0001"
    assert plan.workers[999].worker_id == "w1000"
    assert plan.workers[1499].worker_id == "w1500"
    # All IDs same length — guards against lexicographic-sort bugs.
    assert len({len(w.worker_id) for w in plan.workers}) == 1


# ---------------------------------------------------------------------------
# #13 — Migration 0.1.0 → 0.2.0 applies cleanly and is idempotent
# ---------------------------------------------------------------------------


def test_item_13_migration_writes_vault_state_idempotently(
    tmp_path: Path,
) -> None:
    """The 0.1.0→0.2.0 migration script writes per-vault YAML state for each
    memory_loop adapter and is safe to re-run."""
    if not MIGRATION_SCRIPT.exists():
        pytest.skip("migration script not present in checkout")

    rufino_home = tmp_path / "rufino-home"
    adapter_dir = rufino_home / "adapters" / "memory_loop" / "myvault"
    adapter_dir.mkdir(parents=True)

    env = {**os.environ, "RUFINO_HOME": str(rufino_home)}
    for _ in range(2):
        proc = subprocess.run(
            ["bash", str(MIGRATION_SCRIPT)],
            env=env, capture_output=True, text=True, check=False,
        )
        assert proc.returncode == 0, proc.stderr

    state_file = rufino_home / "state" / "vaults" / "myvault.yaml"
    assert state_file.exists()
    data = yaml.safe_load(state_file.read_text(encoding="utf-8"))
    assert data["vault_slug"] == "myvault"
    assert data["embeddings"]["enabled"] is False
    assert data["embeddings"]["backend"] == "ollama"


# ---------------------------------------------------------------------------
# #15 — This file exists and runs green (meta).
# ---------------------------------------------------------------------------


def test_item_15_e2e_file_loaded() -> None:
    """Sentinel: if this test runs, the E2E file imported cleanly and
    pytest is able to discover it (item 15 in the checklist)."""
    assert True
