import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Any

from rufino.runtime.secrets import SecretStore


@dataclass
class EmailChannel:
    smtp_host: str
    smtp_port: int
    from_address: str
    secrets: SecretStore

    def deliver(self, *, config: dict[str, Any], content: str) -> None:
        msg = EmailMessage()
        msg["From"] = self.from_address
        msg["To"] = config["to"]
        msg["Subject"] = config["subject"]
        msg.set_content(content)

        password = self.secrets.get("rufino-smtp", self.from_address)
        context = ssl.create_default_context()

        if self.smtp_port == 465:
            # Implicit TLS (SMTPS). Most providers require this on 465.
            with smtplib.SMTP_SSL(
                self.smtp_host, self.smtp_port, timeout=30, context=context,
            ) as s:
                s.login(self.from_address, password)
                s.send_message(msg)
            return

        # Submission port (587) or other: STARTTLS with explicit support check.
        with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=30) as s:
            s.ehlo()
            if not s.has_extn("starttls"):
                raise smtplib.SMTPException(
                    f"SMTP server {self.smtp_host}:{self.smtp_port} does not "
                    f"advertise STARTTLS; refusing to log in over plaintext"
                )
            s.starttls(context=context)
            s.ehlo()
            s.login(self.from_address, password)
            s.send_message(msg)
