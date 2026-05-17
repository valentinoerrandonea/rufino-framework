from pathlib import Path
from rufino.engine.process.dispatcher import process_note
from rufino.engine.process.llm_client import StubLLMClient
from rufino.engine.process.context_injectors import StubQueryLayer
from rufino.engine.process.qa_integration import StubQALoop


FIXTURE = Path(__file__).parent / "fixtures" / "adapters" / "process-apunte-clase"


CANNED_LLM_OUTPUT = """---
materia: ml-i
topics: [regresion, gradient-descent]
profesor: mendez
triples:
  - { r: tema-de, o: ml-i }
  - { r: expuesto-por, o: mendez }
tags: [materia/ml-i, tema/regresion, profesor/mendez]
---
Body augmentado.
"""


def test_full_mode_writes_augmented_to_destination(tmp_vault: Path):
    inbox = tmp_vault / "inbox"
    inbox.mkdir()
    note = inbox / "clase3.md"
    note.write_text("Crude apunte sobre regresión logística.")

    (tmp_vault / "_meta").mkdir()
    (tmp_vault / "_meta" / "_tags.md").write_text("# Tags\n")
    (tmp_vault / "_meta" / "_processing-log.md").write_text("# Log\n")

    result = process_note(
        note_path=note,
        vault_root=tmp_vault,
        mode="full",
        adapter_dir=FIXTURE,
        llm_client=StubLLMClient(canned_response=CANNED_LLM_OUTPUT),
        query_layer=StubQueryLayer(),
        qa_loop=StubQALoop(),
    )

    assert result.success, result.message
    destination = tmp_vault / "apuntes" / "ml-i" / "clase3.md"
    assert destination.exists()
    assert "Body augmentado" in destination.read_text()
    assert not note.exists()  # moved
