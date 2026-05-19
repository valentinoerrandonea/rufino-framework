"""Tests for the emit_augmented Ingest dispatcher path.

emit_augmented bypasses the inbox: records come from an external source that
has already augmented them, so they go straight to a Process adapter in
`mode="light"` (tags + processing-log only — no LLM call, no adapter dir read).
"""
from pathlib import Path

import pytest

from rufino.engine.ingest.emit_augmented import dispatch_to_process
from rufino.engine.ingest.runner import IngestResult, run_ingest


def _write_adapter(adapter_dir: Path, *, fetcher_body: str) -> None:
    adapter_dir.mkdir(parents=True, exist_ok=True)
    (adapter_dir / "manifest.yaml").write_text(
        "adapter_name: aug\n"
        "source_name: aug\n"
        "schedule: '* * * * *'\n"
        "auth: {}\n"
        "output_mode: emit_augmented\n"
        "process_inline_with: light-tagger\n",
        encoding="utf-8",
    )
    (adapter_dir / "fetcher.py").write_text(fetcher_body, encoding="utf-8")


# ---------------------------------------------------------------------------
# dispatch_to_process unit tests
# ---------------------------------------------------------------------------


def test_dispatch_to_process_happy_path(tmp_vault: Path, tmp_path: Path):
    """A record with id+content gets written, processed, and reported ok."""
    staging = tmp_path / "staging"
    record = {
        "id": "rec-1",
        "content": "---\ntags: [alpha]\n---\nbody text\n",
    }

    result = dispatch_to_process(
        record=record,
        vault_root=tmp_vault,
        staging_dir=staging,
    )

    assert result["status"] == "ok"
    # light-mode side effects: tag index + processing log
    tag_index = (tmp_vault / "_meta" / "_tags.md").read_text(encoding="utf-8")
    assert "alpha" in tag_index
    assert "rec-1" in tag_index
    log = (tmp_vault / "_meta" / "_processing-log.md").read_text(encoding="utf-8")
    assert "light-processed rec-1" in log


def test_dispatch_to_process_falls_back_to_unknown_id(tmp_vault: Path, tmp_path: Path):
    staging = tmp_path / "staging"
    record = {"content": "---\ntags: [x]\n---\nbody\n"}  # no id

    result = dispatch_to_process(
        record=record,
        vault_root=tmp_vault,
        staging_dir=staging,
    )

    assert result["status"] == "ok"
    # processed under the "unknown" slug
    log = (tmp_vault / "_meta" / "_processing-log.md").read_text(encoding="utf-8")
    assert "light-processed unknown" in log


def test_dispatch_to_process_falls_back_to_str_when_no_content(
    tmp_vault: Path, tmp_path: Path,
):
    staging = tmp_path / "staging"
    record = {"id": "rec-2"}  # no content

    result = dispatch_to_process(
        record=record,
        vault_root=tmp_vault,
        staging_dir=staging,
    )

    # No frontmatter ⇒ no tags ⇒ light still succeeds.
    assert result["status"] == "ok"
    body = (staging / "rec-2.md").read_text(encoding="utf-8")
    assert body == str(record)


def test_dispatch_to_process_moves_to_failed_on_error(
    tmp_vault: Path, tmp_path: Path, monkeypatch,
):
    """When process_note raises, the staged note is moved under staging/failed/."""
    staging = tmp_path / "staging"
    record = {"id": "rec-bad", "content": "x"}

    import rufino.engine.ingest.emit_augmented as ea

    def boom(**_kw):
        raise RuntimeError("process exploded")

    monkeypatch.setattr(ea, "process_note", boom, raising=False)

    # Re-import inside dispatch via the symbol bound at function call time.
    # The function does `from rufino.engine.process.dispatcher import process_note`
    # inside its body, so patch THAT.
    from rufino.engine.process import dispatcher as _disp
    monkeypatch.setattr(_disp, "process_note", boom)

    result = dispatch_to_process(
        record=record,
        vault_root=tmp_vault,
        staging_dir=staging,
    )

    assert result["status"] == "failed"
    assert "process exploded" in result["error"]
    assert (staging / "failed" / "rec-bad.md").exists()
    assert not (staging / "rec-bad.md").exists()


# ---------------------------------------------------------------------------
# runner end-to-end: _run_emit_augmented via run_ingest
# ---------------------------------------------------------------------------


def test_run_emit_augmented_happy_path(tmp_vault: Path, tmp_path: Path):
    adapter = tmp_path / "aug-adapter"
    _write_adapter(
        adapter,
        fetcher_body=(
            "def fetch(since):\n"
            "    return [\n"
            "        {'id': 'a', 'content': '---\\ntags: [t1]\\n---\\nA\\n'},\n"
            "        {'id': 'b', 'content': '---\\ntags: [t2]\\n---\\nB\\n'},\n"
            "    ]\n"
        ),
    )

    result = run_ingest(
        adapter_dir=adapter,
        vault_root=tmp_vault,
        rufino_state_dir=tmp_path / "state",
    )

    assert isinstance(result, IngestResult)
    assert result.facts_emitted == 2
    assert result.errors == []
    log = (tmp_vault / "_meta" / "_processing-log.md").read_text(encoding="utf-8")
    assert "light-processed a" in log
    assert "light-processed b" in log
    # cursor advanced because batch was clean
    cursors_file = tmp_path / "state" / "cursors.json"
    assert cursors_file.exists()
    assert "aug" in cursors_file.read_text(encoding="utf-8")


def test_run_emit_augmented_isolates_failures(
    tmp_vault: Path, tmp_path: Path, monkeypatch,
):
    """One bad record gets quarantined; the rest still process."""
    adapter = tmp_path / "aug-adapter-mixed"
    _write_adapter(
        adapter,
        fetcher_body=(
            "def fetch(since):\n"
            "    return [\n"
            "        {'id': 'good', 'content': '---\\ntags: [ok]\\n---\\nG\\n'},\n"
            "        {'id': 'bad',  'content': '---\\ntags: [x]\\n---\\nB\\n'},\n"
            "    ]\n"
        ),
    )

    from rufino.engine.process import dispatcher as _disp
    real_process_note = _disp.process_note

    def selective(*, note_path: Path, vault_root: Path, mode: str, **kw):
        if note_path.stem == "bad":
            raise RuntimeError("simulated processing failure")
        return real_process_note(
            note_path=note_path, vault_root=vault_root, mode=mode, **kw
        )

    monkeypatch.setattr(_disp, "process_note", selective)

    state = tmp_path / "state"
    result = run_ingest(
        adapter_dir=adapter, vault_root=tmp_vault, rufino_state_dir=state,
    )

    assert result.facts_emitted == 1
    assert result.errors, "expected at least one error from the bad record"
    assert any("simulated processing failure" in e for e in result.errors)

    # cursor must NOT advance when there are errors (consistent with emit_fact)
    cursors_file = state / "cursors.json"
    assert not cursors_file.exists() or "aug" not in cursors_file.read_text(
        encoding="utf-8"
    )

    # quarantined record exists under staging/failed/
    staging = state / "emit_augmented" / "aug"
    assert (staging / "failed" / "bad.md").exists()
