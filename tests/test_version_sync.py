import re
from pathlib import Path

from rufino.version import VERSION


def test_pyproject_version_matches_version_py():
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, flags=re.MULTILINE)
    assert m, "no version line in pyproject.toml"
    assert m.group(1) == VERSION, (
        f"pyproject.toml version {m.group(1)!r} != "
        f"src/rufino/version.py VERSION {VERSION!r}"
    )
