from pathlib import Path
from rufino.engine.process.helpers.indices import update_tag_index, append_to_log
from rufino.engine.process.helpers.concepts import promote_concepts
from rufino.engine.process.helpers.persons import register_persons


def test_tag_index_appends_note(tmp_vault: Path):
    tag_index = tmp_vault / "_meta" / "_tags.md"
    tag_index.parent.mkdir()
    tag_index.write_text("# Tags\n")

    update_tag_index(tag_index, tag="materia/ml-i", note_slug="2026-05-16-clase")

    content = tag_index.read_text()
    assert "materia/ml-i" in content
    assert "2026-05-16-clase" in content


def test_log_appends(tmp_vault: Path):
    log = tmp_vault / "_meta" / "_processing-log.md"
    log.parent.mkdir()
    log.write_text("# Log\n")

    append_to_log(log, message="processed clase3")
    content = log.read_text()
    assert "processed clase3" in content


def test_concept_promotion_threshold(tmp_vault: Path):
    conceptos_dir = tmp_vault / "conceptos"
    conceptos_dir.mkdir()

    promoted = promote_concepts(
        conceptos_dir,
        mentions={"regresion-logistica": 2, "isolated-concept": 1},
        threshold=2,
    )
    assert "regresion-logistica" in promoted
    assert "isolated-concept" not in promoted
    assert (conceptos_dir / "regresion-logistica.md").exists()


def test_register_persons_creates_files(tmp_vault: Path):
    people_dir = tmp_vault / "personas"
    people_dir.mkdir()

    created = register_persons(people_dir, persons=["mendez", "garcia"])
    assert "mendez" in created
    assert (people_dir / "mendez.md").exists()
    assert (people_dir / "garcia.md").exists()


def test_register_persons_idempotent(tmp_vault: Path):
    people_dir = tmp_vault / "personas"
    people_dir.mkdir()
    (people_dir / "mendez.md").write_text("# Mendez\n(existing)\n")

    created = register_persons(people_dir, persons=["mendez"])
    assert created == []
    assert (people_dir / "mendez.md").read_text() == "# Mendez\n(existing)\n"
