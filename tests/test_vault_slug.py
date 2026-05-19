"""Unit tests for compute_vault_slug.

The slug is the per-vault identifier used to name hooks, commands, and the MCP
server entry. It must be stable, filesystem-safe, and never empty.
"""
import pytest
from pathlib import Path

from rufino.runtime.vault_slug import compute_vault_slug


def test_simple_lowercase_name(tmp_path: Path):
    assert compute_vault_slug(tmp_path / "facultad") == "facultad"


def test_uppercase_is_lowercased(tmp_path: Path):
    assert compute_vault_slug(tmp_path / "Work") == "work"


def test_spaces_become_hyphens(tmp_path: Path):
    assert compute_vault_slug(tmp_path / "my notes") == "my-notes"


def test_underscores_become_hyphens(tmp_path: Path):
    assert compute_vault_slug(tmp_path / "study_2026") == "study-2026"


def test_collapses_repeated_separators(tmp_path: Path):
    assert compute_vault_slug(tmp_path / "a  b__c") == "a-b-c"


def test_strips_leading_trailing_separators(tmp_path: Path):
    assert compute_vault_slug(tmp_path / "--foo--") == "foo"


def test_empty_basename_raises(tmp_path: Path):
    # A path whose basename normalizes to empty (only specials) must fail loudly.
    with pytest.raises(ValueError, match="empty slug"):
        compute_vault_slug(tmp_path / "!!!")


def test_two_vaults_with_same_basename_collide(tmp_path: Path):
    """Documented limitation: slug is basename-only. Caller is expected to keep
    vault directory names unique on the same machine."""
    a = tmp_path / "a" / "study"
    b = tmp_path / "b" / "study"
    assert compute_vault_slug(a) == compute_vault_slug(b)
