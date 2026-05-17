from pathlib import Path
from rufino.engine.process.dispatcher import process_note, ProcessResult


def test_light_mode_updates_indices_only(tmp_vault: Path):
    inbox = tmp_vault / "inbox"
    inbox.mkdir()
    note = inbox / "test.md"
    note.write_text(
        "---\n"
        "tags: [materia/ml-i, tema/regresion]\n"
        "triples:\n"
        "  - { r: tema-de, o: ml-i }\n"
        "---\n"
        "Body unchanged.\n"
    )

    (tmp_vault / "_meta").mkdir()
    (tmp_vault / "_meta" / "_tags.md").write_text("# Tags\n")
    (tmp_vault / "_meta" / "_processing-log.md").write_text("# Log\n")

    result = process_note(
        note_path=note,
        vault_root=tmp_vault,
        mode="light",
    )

    assert result.success
    assert "Body unchanged." in note.read_text()
    tag_index = (tmp_vault / "_meta" / "_tags.md").read_text()
    assert "materia/ml-i" in tag_index
