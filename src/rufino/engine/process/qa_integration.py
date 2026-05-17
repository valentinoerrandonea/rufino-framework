from dataclasses import dataclass, field
from typing import Protocol


class QALoop(Protocol):
    def ask_user(
        self,
        *,
        template_name: str,
        context: dict,
        adapter_name: str,
        adapter_state: dict,
    ) -> str: ...


@dataclass
class StubQALoop:
    """Stub: returns a pre-canned answer or 'PENDING' if not configured.

    Signature matches the real QALoopAPI.ask_user (plan 6) so the stub is
    drop-in replaceable.
    """
    canned_answers: dict[str, str] = field(default_factory=dict)
    calls: list[tuple[str, dict]] = field(default_factory=list)

    def ask_user(
        self,
        *,
        template_name: str,
        context: dict,
        adapter_name: str = "stub-process",
        adapter_state: dict | None = None,
    ) -> str:
        self.calls.append((template_name, context))
        return self.canned_answers.get(template_name, "PENDING")
