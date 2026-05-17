from typing import Protocol, Any, runtime_checkable


@runtime_checkable
class Channel(Protocol):
    """Common interface for delivery channels (file, email, webhook, push)."""

    def deliver(self, *, config: dict[str, Any], content: str) -> None: ...
