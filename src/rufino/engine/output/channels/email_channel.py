import smtplib
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

        with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=30) as s:
            s.starttls()
            s.login(self.from_address, password)
            s.send_message(msg)
