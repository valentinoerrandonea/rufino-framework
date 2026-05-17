import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


class InvalidWebhookSchemeError(Exception):
    """Raised when a webhook URL uses a non-http(s) scheme."""


_ALLOWED_SCHEMES = {"https", "http"}


@dataclass
class WebhookChannel:
    def deliver(self, *, config: dict[str, Any], content: str) -> None:
        url = config["url"]
        scheme = urllib.parse.urlparse(url).scheme
        if scheme not in _ALLOWED_SCHEMES:
            raise InvalidWebhookSchemeError(
                f"Webhook URL scheme must be http(s), got {scheme!r}"
            )
        payload = json.dumps({"content": content}).encode("utf-8")
        req = urllib.request.Request(
            url=url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as _resp:  # noqa: S310
            pass
