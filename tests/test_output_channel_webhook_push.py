import pytest
from unittest.mock import patch, MagicMock
from rufino.engine.output.channels.webhook_channel import (
    WebhookChannel,
    InvalidWebhookSchemeError,
)
from rufino.engine.output.channels.push_channel import PushChannel


def test_webhook_posts_json():
    ch = WebhookChannel()
    with patch("urllib.request.urlopen") as mock_open:
        mock_open.return_value.__enter__.return_value.read.return_value = b""
        ch.deliver(
            config={"url": "https://example.com/hook"},
            content="message body",
        )
        mock_open.assert_called_once()
        req = mock_open.call_args[0][0]
        assert req.full_url == "https://example.com/hook"


def test_push_invokes_osascript_on_darwin():
    ch = PushChannel(platform="Darwin")
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        ch.deliver(
            config={"title": "Rufino"},
            content="Hello",
        )
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "osascript"


def test_push_invokes_notify_send_on_linux():
    ch = PushChannel(platform="Linux")
    with patch("subprocess.run") as mock_run:
        ch.deliver(
            config={"title": "Rufino"},
            content="Hello",
        )
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "notify-send"
        assert "--" in cmd


def test_push_linux_blocks_flag_injection():
    ch = PushChannel(platform="Linux")
    with patch("subprocess.run") as mock_run:
        ch.deliver(
            config={"title": "--icon=/etc/passwd"},
            content="x",
        )
        cmd = mock_run.call_args[0][0]
        sep_idx = cmd.index("--")
        # title must appear AFTER the -- separator so notify-send doesn't parse it as a flag
        assert cmd.index("--icon=/etc/passwd") > sep_idx


def test_webhook_rejects_file_scheme():
    ch = WebhookChannel()
    with pytest.raises(InvalidWebhookSchemeError):
        ch.deliver(
            config={"url": "file:///etc/passwd"},
            content="x",
        )


def test_push_escapes_applescript_injection():
    ch = PushChannel(platform="Darwin")
    with patch("subprocess.run") as mock_run:
        ch.deliver(
            config={"title": 'evil" trailing'},
            content='also" malicious',
        )
        script = mock_run.call_args[0][0][2]
        # both injected " got escaped, so we see 2 instances of \" plus 4 delimiter "
        assert script.count('\\"') == 2
        # 4 delimiter quotes + 2 quote-chars inside \" = 6 total
        assert script.count('"') == 6
