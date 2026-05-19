"""Parity test: the bash slug derivation in install.sh must match
compute_vault_slug for the inputs we care about.

If these drift, `./install.sh` would register `ask-rufino-<bash-slug>`
while `rufino materialize` would later register `ask-rufino-<py-slug>`
for the same vault — leaving two stale MCP entries in ~/.claude.json.
"""
import subprocess
from pathlib import Path

import pytest

from rufino.runtime.vault_slug import compute_vault_slug


# Mirrors install.sh:114-115. If you change either, change both.
_BASH_SLUG_SCRIPT = """\
set -e
basename "$1" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//'
"""


def _bash_slug(vault_path: str) -> str:
    """Run the same shell pipeline as install.sh and return its output."""
    result = subprocess.run(
        ["bash", "-c", _BASH_SLUG_SCRIPT, "_", vault_path],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


@pytest.mark.parametrize("vault_basename", [
    "facultad",
    "Work",
    "my notes",
    "study_2026",
    "a  b__c",
    "study-2026",
    "weird.name",
    "vault.with.dots",
])
def test_bash_and_python_slug_agree(tmp_path: Path, vault_basename: str):
    vault_path = tmp_path / vault_basename
    py = compute_vault_slug(vault_path)
    sh = _bash_slug(str(vault_path))
    assert py == sh, (
        f"slug parity broken for {vault_basename!r}: "
        f"python={py!r} bash={sh!r}"
    )


def test_bash_pipeline_in_install_sh_matches_test_constant():
    """If someone edits install.sh's slug pipeline without updating this
    test's constant, this guard catches the drift."""
    install_sh = Path(__file__).parent.parent / "install.sh"
    body = install_sh.read_text(encoding="utf-8")
    # The install.sh form spans two lines and uses double quotes around
    # $RUFINO_VAULT — compare the *normalized* tail (everything after `basename `)
    # to the test's pipeline tail.
    expected_tail = "tr '[:upper:]' '[:lower:]'"
    expected_sed = "sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//'"
    assert expected_tail in body, (
        "install.sh no longer pipes through `tr` for lowercasing — the bash "
        "slug derivation has drifted from compute_vault_slug. Update "
        "_BASH_SLUG_PIPELINE in this test (and re-verify parity)."
    )
    assert expected_sed in body, (
        "install.sh no longer uses the expected sed regex for slug "
        "normalization. Update _BASH_SLUG_PIPELINE in this test."
    )
