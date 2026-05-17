"""Security + invariance tests for the full-mode dispatcher.

Covers code-review findings:
- Critical 1: path traversal via LLM-controlled frontmatter values.
- Critical 2: source preservation if any post-LLM step fails.
"""
from pathlib import Path
import pytest
from rufino.engine.process.dispatcher import process_note, DestinationOutsideVaultError
from rufino.engine.process.llm_client import StubLLMClient
from rufino.engine.process.context_injectors import StubQueryLayer
from rufino.engine.process.qa_integration import StubQALoop


FIXTURE = Path(__file__).parent / "fixtures" / "adapters" / "process-apunte-clase"


TRAVERSAL_OUTPUT = """---
materia: ../../../escaped
topics: [evil]
triples:
  - { r: tema-de, o: x }
tags: [materia/escaped]
---
Pwned.
"""


def test_destination_outside_vault_is_rejected(tmp_vault: Path):
    inbox = tmp_vault / "inbox"
    inbox.mkdir()
    note = inbox / "evil.md"
    note.write_text("crude")
    (tmp_vault / "_meta").mkdir()
    (tmp_vault / "_meta" / "_tags.md").write_text("# Tags\n")
    (tmp_vault / "_meta" / "_processing-log.md").write_text("# Log\n")

    with pytest.raises(DestinationOutsideVaultError):
        process_note(
            note_path=note,
            vault_root=tmp_vault,
            mode="full",
            adapter_dir=FIXTURE,
            llm_client=StubLLMClient(canned_response=TRAVERSAL_OUTPUT),
            query_layer=StubQueryLayer(),
            qa_loop=StubQALoop(),
        )

    # Source preserved on rejection.
    assert note.exists()
    assert note.read_text() == "crude"


VALID_LLM_OUTPUT = """---
materia: ml-i
topics: [t]
triples:
  - { r: tema-de, o: ml-i }
tags: [materia/ml-i]
---
Augmented.
"""


def test_source_preserved_when_index_update_fails(tmp_vault: Path, monkeypatch):
    """If a post-write index step fails, the source note must remain so the user can retry."""
    inbox = tmp_vault / "inbox"
    inbox.mkdir()
    note = inbox / "n.md"
    note.write_text("crude")
    (tmp_vault / "_meta").mkdir()
    (tmp_vault / "_meta" / "_tags.md").write_text("# Tags\n")
    (tmp_vault / "_meta" / "_processing-log.md").write_text("# Log\n")

    import rufino.engine.process.dispatcher as disp

    def boom(*args, **kwargs):
        raise RuntimeError("simulated index failure")

    monkeypatch.setattr(disp, "update_tag_index", boom)

    with pytest.raises(RuntimeError, match="simulated index failure"):
        process_note(
            note_path=note,
            vault_root=tmp_vault,
            mode="full",
            adapter_dir=FIXTURE,
            llm_client=StubLLMClient(canned_response=VALID_LLM_OUTPUT),
            query_layer=StubQueryLayer(),
            qa_loop=StubQALoop(),
        )

    # Source still there — user can re-run after fixing the underlying issue.
    assert note.exists(), "source note should not be removed when downstream steps fail"
    assert note.read_text() == "crude"
