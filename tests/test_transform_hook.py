"""Tests for runtime/transform_hook.py — Task 4.1 of the v0.2.0 plan.

Uses real subprocess invocation against tiny inline scripts (no mocking) so
the contract — JSON-in/stdin, JSON-out/stdout, error -> TransformHookError —
is exercised end-to-end.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rufino.runtime.transform_hook import TransformHookError, run_transform_hook


def _write_script(tmp_path: Path, body: str) -> Path:
    script = tmp_path / "hook.py"
    script.write_text(body, encoding="utf-8")
    return script


def test_happy_path_hook_modifies_dict(tmp_path: Path) -> None:
    """A hook that reads stdin, mutates the payload, and writes JSON to stdout
    round-trips through ``run_transform_hook`` cleanly."""
    script = _write_script(
        tmp_path,
        (
            "import json, sys\n"
            "data = json.loads(sys.stdin.read())\n"
            "data['extra'] = 'added-by-hook'\n"
            "data['count'] = data.get('count', 0) + 1\n"
            "sys.stdout.write(json.dumps(data))\n"
        ),
    )

    out = run_transform_hook(script, {"count": 41, "title": "foo"})

    assert out == {"count": 42, "title": "foo", "extra": "added-by-hook"}


def test_timeout_raises_transform_hook_error(tmp_path: Path) -> None:
    """A hook that sleeps past the timeout surfaces as ``TransformHookError``."""
    script = _write_script(
        tmp_path,
        "import time\n"
        "time.sleep(5)\n",
    )

    with pytest.raises(TransformHookError, match="timeout"):
        run_transform_hook(script, {"x": 1}, timeout=0.5)


def test_non_zero_exit_raises_transform_hook_error(tmp_path: Path) -> None:
    """A hook that exits with a non-zero status surfaces as ``TransformHookError``
    and includes the exit code + stderr excerpt in the message."""
    script = _write_script(
        tmp_path,
        (
            "import sys\n"
            "sys.stderr.write('boom: something went wrong\\n')\n"
            "sys.exit(3)\n"
        ),
    )

    with pytest.raises(TransformHookError) as exc:
        run_transform_hook(script, {"x": 1})

    msg = str(exc.value)
    assert "exited 3" in msg
    assert "boom" in msg


def test_malformed_json_raises_transform_hook_error(tmp_path: Path) -> None:
    """A hook that prints non-JSON on stdout (but exits 0) surfaces as
    ``TransformHookError`` mentioning malformed JSON."""
    script = _write_script(
        tmp_path,
        "import sys\n"
        "sys.stdout.write('this is not json at all\\n')\n",
    )

    with pytest.raises(TransformHookError, match="malformed JSON"):
        run_transform_hook(script, {"x": 1})


def test_run_transform_hook_rejects_non_dict_json(tmp_path: Path) -> None:
    """A hook that prints valid JSON which is not an object (e.g. a list or a
    bare number) must surface as ``TransformHookError`` — the contract is
    JSON-object-in / JSON-object-out, so callers can rely on ``dict[str, Any]``."""
    script = _write_script(
        tmp_path,
        "import sys\n"
        "sys.stdout.write('[1, 2, 3]')\n",
    )

    with pytest.raises(TransformHookError, match="non-dict"):
        run_transform_hook(script, {"x": 1})


def test_run_transform_hook_coerces_datetime_to_string(tmp_path: Path) -> None:
    """A frontmatter value that's a datetime.date round-trips as a string.

    PyYAML parses ``created: 2026-05-19`` into ``datetime.date`` by default,
    which is not JSON-native. ``json.dumps`` would raise ``TypeError`` were
    it not for the ``default=str`` hardening — and that ``TypeError`` is not
    in the (OSError, UnicodeDecodeError, FrontmatterError) catch around the
    Process call site, so it would abort the batch.
    """
    from datetime import date
    script = tmp_path / "echo.py"
    script.write_text(
        "import json, sys\n"
        "data = json.loads(sys.stdin.read())\n"
        "sys.stdout.write(json.dumps({'received_kind': type(data['created']).__name__,\n"
        "                              'received_value': data['created']}))\n"
    )
    script.chmod(0o755)
    out = run_transform_hook(script, {"created": date(2026, 5, 19)})
    assert out == {"received_kind": "str", "received_value": "2026-05-19"}


def test_input_payload_is_delivered_intact(tmp_path: Path) -> None:
    """Round-trip a non-trivial payload through stdin to verify encoding."""
    script = _write_script(
        tmp_path,
        (
            "import json, sys\n"
            "sys.stdout.write(sys.stdin.read())\n"
        ),
    )

    payload = {
        "title": "café — résumé",
        "tags": ["a", "b", "c"],
        "nested": {"k": [1, 2, 3], "flag": True, "none": None},
    }
    out = run_transform_hook(script, payload)

    assert out == payload
    # Sanity: ensure the round-trip preserved unicode (not escaped to ascii)
    assert json.dumps(out, ensure_ascii=False) == json.dumps(payload, ensure_ascii=False)
