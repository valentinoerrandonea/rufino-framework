from pathlib import Path
from rufino.engine.output.channels.file_channel import FileChannel
from rufino.engine.output.channels.base import Channel


def test_file_channel_writes_to_vault(tmp_vault: Path):
    ch = FileChannel(vault_root=tmp_vault)
    ch.deliver(
        config={"path": "general/digests/2026-W20.md"},
        content="# Digest\nBody.\n",
    )
    out = tmp_vault / "general" / "digests" / "2026-W20.md"
    assert out.exists()
    assert "Digest" in out.read_text()


def test_file_channel_protocol():
    assert isinstance(FileChannel(vault_root=Path("/x")), Channel)


def test_file_channel_creates_parents(tmp_vault: Path):
    ch = FileChannel(vault_root=tmp_vault)
    ch.deliver(
        config={"path": "deeply/nested/path/out.md"},
        content="content",
    )
    assert (tmp_vault / "deeply" / "nested" / "path" / "out.md").exists()
