from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class LLMResponse:
    text: str


@runtime_checkable
class LLMClient(Protocol):
    def complete(self, *, prompt: str, model: str) -> LLMResponse: ...


@dataclass
class StubLLMClient:
    """Stub for tests. Returns a pre-canned response and records every call."""
    canned_response: str
    calls: list[tuple[str, str]] = field(default_factory=list)

    def complete(self, *, prompt: str, model: str) -> LLMResponse:
        self.calls.append((prompt, model))
        return LLMResponse(text=self.canned_response)
