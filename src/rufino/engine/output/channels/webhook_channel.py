import json
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass
class WebhookChannel:
    def deliver(self, *, config: dict[str, Any], content: str) -> None:
        payload = json.dumps({"content": content}).encode("utf-8")
        req = urllib.request.Request(
            url=config["url"],
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as _resp:
            pass
