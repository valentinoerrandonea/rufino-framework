import pytest

from rufino.engine.process.manifest import (
    ManifestParseError,
    parse_worker_manifest,
)


_MIN_MANIFEST = """
adapter_name: x
note_type: x
applies_when:
  source_dir: inbox/
  matches_pattern: ["*.md"]
llm: sonnet
mode_default: full
output_schema:
  required:
    title: string
triple_vocabulary:
  - tema-de
tag_axes:
  - axis: materia
    format: "materia/{slug}"
destination_path: "apuntes/{slug}.md"
"""


def test_batch_size_defaults_to_10_when_absent():
    m = parse_worker_manifest(_MIN_MANIFEST)
    assert m.batch_size == 10


def test_batch_size_respects_manifest_value():
    m = parse_worker_manifest(_MIN_MANIFEST + "\nbatch_size: 25\n")
    assert m.batch_size == 25


def test_batch_size_zero_rejected():
    with pytest.raises(ManifestParseError, match="batch_size"):
        parse_worker_manifest(_MIN_MANIFEST + "\nbatch_size: 0\n")


def test_batch_size_negative_rejected():
    with pytest.raises(ManifestParseError, match="batch_size"):
        parse_worker_manifest(_MIN_MANIFEST + "\nbatch_size: -1\n")


def test_batch_size_non_int_rejected():
    with pytest.raises(ManifestParseError, match="batch_size"):
        parse_worker_manifest(_MIN_MANIFEST + "\nbatch_size: foo\n")
