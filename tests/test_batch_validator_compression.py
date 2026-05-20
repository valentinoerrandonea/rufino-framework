import logging
from pathlib import Path

import pytest

from rufino.engine.process.batch.validator import check_compression_ratio


def _write_note(path: Path, body_words: int) -> None:
    body = " ".join(["palabra"] * body_words)
    path.write_text(f"---\nslug: nota\n---\n{body}\n", encoding="utf-8")


def test_check_compression_ratio_warns_when_below_floor(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
):
    original = tmp_path / "original.md"
    augmented = tmp_path / "augmented.md"
    _write_note(original, 1000)
    _write_note(augmented, 400)  # ratio = 0.4

    caplog.set_level(
        logging.WARNING, logger="rufino.engine.process.batch.validator",
    )
    result = check_compression_ratio(
        original=original, augmented=augmented, floor=0.9,
    )
    assert result is not None
    assert result.ratio == pytest.approx(0.4, abs=0.01)
    assert result.below_floor is True
    assert any(
        "compression below floor" in r.message.lower()
        for r in caplog.records
    )


def test_check_compression_ratio_silent_when_above_floor(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
):
    original = tmp_path / "original.md"
    augmented = tmp_path / "augmented.md"
    _write_note(original, 1000)
    _write_note(augmented, 950)  # ratio = 0.95

    caplog.set_level(
        logging.WARNING, logger="rufino.engine.process.batch.validator",
    )
    result = check_compression_ratio(
        original=original, augmented=augmented, floor=0.9,
    )
    assert result is not None
    assert result.below_floor is False
    assert not any(
        "compression below floor" in r.message.lower()
        for r in caplog.records
    )


def test_check_compression_ratio_skipped_when_floor_is_none(tmp_path: Path):
    original = tmp_path / "original.md"
    augmented = tmp_path / "augmented.md"
    _write_note(original, 1000)
    _write_note(augmented, 100)

    result = check_compression_ratio(
        original=original, augmented=augmented, floor=None,
    )
    assert result is None
