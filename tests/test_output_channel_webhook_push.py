from unittest.mock import patch, MagicMock
from rufino.engine.output.channels.webhook_channel import WebhookChannel
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
