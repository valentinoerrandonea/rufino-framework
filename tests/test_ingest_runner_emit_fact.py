from pathlib import Path
from rufino.engine.ingest.runner import run_ingest, IngestResult


FIXTURE = Path(__file__).parent / "fixtures" / "adapters" / "ingest-belo"


def test_emit_fact_writes_facts_to_vault(tmp_vault: Path, tmp_path: Path):
    result = run_ingest(
        adapter_dir=FIXTURE,
        vault_root=tmp_vault,
        rufino_state_dir=tmp_path / ".rufino-state",
    )

    assert isinstance(result, IngestResult)
    assert result.facts_emitted == 2

    facts_dir = tmp_vault / "belo" / "facts"
    fact_files = list(facts_dir.glob("*.md"))
    assert len(fact_files) == 2


def test_emit_fact_dedup_on_rerun(tmp_vault: Path, tmp_path: Path):
    state = tmp_path / ".rufino-state"
    run_ingest(adapter_dir=FIXTURE, vault_root=tmp_vault, rufino_state_dir=state)
    result_2 = run_ingest(adapter_dir=FIXTURE, vault_root=tmp_vault, rufino_state_dir=state)
    assert result_2.facts_emitted == 0
    assert result_2.facts_skipped == 2
