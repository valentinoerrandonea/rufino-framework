from pathlib import Path
from rufino.engine.ingest.runner import run_ingest


FIXTURE = Path(__file__).parent / "fixtures" / "adapters" / "ingest-drive-pdfs"


def test_import_raw_writes_to_inbox(tmp_vault: Path, tmp_path: Path):
    inbox = tmp_vault / "rufino" / "inbox"
    process_calls = []

    def stub_process_hook(note_path: Path, vault_root: Path, adapter_name: str):
        process_calls.append((note_path, vault_root, adapter_name))

    run_ingest(
        adapter_dir=FIXTURE,
        vault_root=tmp_vault,
        rufino_state_dir=tmp_path / ".rufino-state",
        process_hook=stub_process_hook,
    )

    assert (inbox / "clase4-svm.md").exists()
    assert (inbox / "clase5-trees.md").exists()
    assert len(process_calls) == 2
    assert all(c[2] == "apunte-clase" for c in process_calls)


def test_import_raw_defer_skips_process_call(tmp_vault: Path, tmp_path: Path):
    fixture_defer = tmp_path / "defer-adapter"
    fixture_defer.mkdir()
    (fixture_defer / "manifest.yaml").write_text(
        "adapter_name: defer\nsource_name: defer\nschedule: '0 0 * * *'\n"
        "auth: {}\noutput_mode: import_raw\ntarget_inbox: inbox/\n"
        "process_with: x\ntrigger: defer\n"
    )
    (fixture_defer / "fetcher.py").write_text(
        "def fetch(since):\n    return [{'filename':'a.md','content':'x'}]\n"
    )

    process_calls = []
    run_ingest(
        adapter_dir=fixture_defer,
        vault_root=tmp_vault,
        rufino_state_dir=tmp_path / ".rufino-state",
        process_hook=lambda *a, **kw: process_calls.append(True),
    )
    assert (tmp_vault / "inbox" / "a.md").exists()
    assert process_calls == []
