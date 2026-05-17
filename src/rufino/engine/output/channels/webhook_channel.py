import ipaddress
import json
import socket
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


class InvalidWebhookSchemeError(Exception):
    """Raised when a webhook URL uses a non-http(s) scheme."""


class InvalidWebhookTargetError(Exception):
    """Raised when a webhook URL resolves to a disallowed host (SSRF guard)."""


_ALLOWED_SCHEMES = {"https", "http"}
_BLOCKED_HOSTNAMES = {"localhost", "localhost.localdomain", "ip6-localhost"}


def _is_blocked_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _assert_safe_target(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise InvalidWebhookSchemeError(
            f"Webhook URL scheme must be http(s), got {parsed.scheme!r}"
        )
    host = (parsed.hostname or "").lower()
    if not host:
        raise InvalidWebhookTargetError("Webhook URL missing hostname")
    if host in _BLOCKED_HOSTNAMES:
        raise InvalidWebhookTargetError(f"Blocked hostname: {host!r}")
    if _is_blocked_ip(host.strip("[]")):
        raise InvalidWebhookTargetError(f"Blocked IP literal: {host!r}")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise InvalidWebhookTargetError(f"DNS lookup failed for {host!r}: {e}")
    for info in infos:
        ip_str = info[4][0]
        if _is_blocked_ip(ip_str):
            raise InvalidWebhookTargetError(
                f"Host {host!r} resolves to blocked IP {ip_str}"
            )


@dataclass
class WebhookChannel:
    def deliver(self, *, config: dict[str, Any], content: str) -> None:
        url = config["url"]
        _assert_safe_target(url)
        payload = json.dumps({"content": content}).encode("utf-8")
        req = urllib.request.Request(
            url=url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as _resp:  # noqa: S310
            pass
