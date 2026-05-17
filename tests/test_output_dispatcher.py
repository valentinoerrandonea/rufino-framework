import pytest
from pathlib import Path
from rufino.engine.output.dispatcher import dispatch_output, OutputResult
from rufino.engine.process.context_injectors import StubQueryLayer
from rufino.engine.output.channels.file_channel import FileChannel


FIXTURE = Path(__file__).parent / "fixtures" / "adapters" / "output-digest-semanal-facultad"


def test_cron_trigger_renders_and_writes(tmp_vault: Path):
    query = StubQueryLayer(canned_results={
        "created >= 7 days ago": ["apuntes/ml-i/clase1.md", "apuntes/ml-i/clase2.md"],
    })
    channels = {"file": FileChannel(vault_root=tmp_vault)}

    result = dispatch_output(
        adapter_dir=FIXTURE,
        query=query,
        channels=channels,
        event_context={},
    )

    assert isinstance(result, OutputResult)
    assert result.deliveries == 1
    out = tmp_vault / "general" / "digests" / "W20.md"
    assert out.exists()
    content = out.read_text()
    assert "apuntes/ml-i/clase1.md" in content
    assert "apuntes/ml-i/clase2.md" in content


def test_unknown_channel_in_manifest_raises(tmp_vault: Path):
    query = StubQueryLayer()
    channels: dict = {}

    with pytest.raises(Exception, match="file"):
        dispatch_output(
            adapter_dir=FIXTURE,
            query=query,
            channels=channels,
            event_context={},
        )
