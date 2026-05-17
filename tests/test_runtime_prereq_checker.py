from unittest.mock import patch

import pytest

from rufino.runtime.prereq_checker import (
    BUILT_IN_CHECKS,
    PrereqCheck,
    check_prereq,
)


def test_command_check_passes_when_present():
    with patch("shutil.which", return_value="/opt/homebrew/bin/ollama"):
        result = check_prereq(PrereqCheck(
            name="ollama",
            kind="command",
            target="ollama",
            for_feature="embeddings",
        ))
    assert result.ok


def test_command_check_fails_when_missing():
    with patch("shutil.which", return_value=None):
        result = check_prereq(PrereqCheck(
            name="ollama",
            kind="command",
            target="ollama",
            for_feature="embeddings",
        ))
    assert not result.ok
    assert "embeddings" in result.message


def test_python_version_check():
    result = check_prereq(PrereqCheck(
        name="python311",
        kind="python_min_version",
        target="3.11",
        for_feature="transform hooks",
    ))
    # Project requires >=3.11 in pyproject.toml so test runner is also >=3.11
    assert result.ok


def test_unknown_kind_raises():
    with pytest.raises(ValueError, match="Unknown check kind"):
        check_prereq(PrereqCheck(
            name="x", kind="weather", target="sun", for_feature="anything",
        ))


def test_built_in_checks_present():
    names = {c.name for c in BUILT_IN_CHECKS}
    assert "ollama" in names
    assert "security_cli" in names
    assert "python311" in names
    assert "node" in names
    assert "gh_cli" in names
    assert "ripgrep" in names
