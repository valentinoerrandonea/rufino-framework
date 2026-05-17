from pathlib import Path
from rufino.engine.process.dispatcher import process_note
from rufino.engine.process.llm_client import StubLLMClient
from rufino.engine.process.context_injectors import StubQueryLayer
from rufino.engine.process.qa_integration import StubQALoop


FIXTURE = Path(__file__).parent / "fixtures" / "adapters" / "process-apunte-clase"


def test_full_process_pipeline_end_to_end(tmp_vault: Path):
    inbox = tmp_vault / "inbox"
    inbox.mkdir()
    note = inbox / "smoke.md"
    note.write_text("Apunte crudo de smoke test.")

    (tmp_vault / "_meta").mkdir()
    (tmp_vault / "_meta" / "_tags.md").write_text("# Tags\n")
    (tmp_vault / "_meta" / "_processing-log.md").write_text("# Log\n")

    canned = """---
materia: ml-i
topics: [smoke]
triples:
  - { r: tema-de, o: ml-i }
tags: [materia/ml-i, tema/smoke]
---
Augmentado smoke.
"""
    result = process_note(
        note_path=note,
        vault_root=tmp_vault,
        mode="full",
        adapter_dir=FIXTURE,
        llm_client=StubLLMClient(canned_response=canned),
        query_layer=StubQueryLayer(),
        qa_loop=StubQALoop(),
    )

    assert result.success
    moved = tmp_vault / "apuntes" / "ml-i" / "smoke.md"
    assert moved.exists()
    assert "Augmentado smoke" in moved.read_text()
    assert "materia/ml-i" in (tmp_vault / "_meta" / "_tags.md").read_text()
