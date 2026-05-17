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


import pytest


def test_email_channel_uses_smtps_when_port_465():
    secrets = InMemorySecretStore()
    secrets.set("rufino-smtp", "user@example.com", "pw")
    ch = EmailChannel(
        smtp_host="smtp.example.com",
        smtp_port=465,
        from_address="user@example.com",
        secrets=secrets,
    )
    with patch("smtplib.SMTP_SSL") as mock_smtps, patch("smtplib.SMTP") as mock_smtp:
        instance = MagicMock()
        mock_smtps.return_value.__enter__.return_value = instance
        ch.deliver(config={"to": "x@example.com", "subject": "T"}, content="b")
        mock_smtps.assert_called_once()
        mock_smtp.assert_not_called()


def test_email_channel_refuses_login_when_starttls_unsupported():
    secrets = InMemorySecretStore()
    secrets.set("rufino-smtp", "user@example.com", "pw")
    ch = EmailChannel(
        smtp_host="smtp.example.com",
        smtp_port=587,
        from_address="user@example.com",
        secrets=secrets,
    )
    with patch("smtplib.SMTP") as mock_smtp:
        instance = MagicMock()
        mock_smtp.return_value.__enter__.return_value = instance
        # Pretend STARTTLS is not advertised after EHLO.
        instance.has_extn.return_value = False
        with pytest.raises(smtplib.SMTPException, match="STARTTLS"):
            ch.deliver(config={"to": "x@example.com", "subject": "T"}, content="b")
        instance.login.assert_not_called()
        instance.send_message.assert_not_called()


import smtplib  # noqa: E402
