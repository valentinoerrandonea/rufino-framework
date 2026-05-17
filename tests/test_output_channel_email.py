from unittest.mock import patch, MagicMock
from rufino.engine.output.channels.email_channel import EmailChannel
from rufino.runtime.secrets import InMemorySecretStore


def test_email_channel_invokes_smtp():
    secrets = InMemorySecretStore()
    secrets.set("rufino-smtp", "user@example.com", "app-password-xyz")

    ch = EmailChannel(
        smtp_host="smtp.gmail.com",
        smtp_port=587,
        from_address="user@example.com",
        secrets=secrets,
    )

    with patch("smtplib.SMTP") as mock_smtp:
        instance = MagicMock()
        mock_smtp.return_value.__enter__.return_value = instance
        ch.deliver(
            config={"to": "dest@example.com", "subject": "Test"},
            content="Body.",
        )
        instance.starttls.assert_called_once()
        instance.login.assert_called_once_with("user@example.com", "app-password-xyz")
        instance.send_message.assert_called_once()
