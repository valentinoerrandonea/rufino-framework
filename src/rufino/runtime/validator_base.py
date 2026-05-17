from dataclasses import dataclass, field
from typing import Protocol, Any, runtime_checkable


@dataclass(frozen=True)
class ValidationError:
    field: str
    message: str
    line: int | None = None


@dataclass(frozen=True)
class ValidationWarning:
    field: str
    message: str
    line: int | None = None


@dataclass
class ValidationResult:
    errors: list[ValidationError] = field(default_factory=list)
    warnings: list[ValidationWarning] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0

    def report(self) -> str:
        """Render result for user-facing display."""
        lines: list[str] = []
        for e in self.errors:
            loc = f"line {e.line}: " if e.line else ""
            lines.append(f"ERROR  {e.field}: {loc}{e.message}")
        for w in self.warnings:
            loc = f"line {w.line}: " if w.line else ""
            lines.append(f"WARN   {w.field}: {loc}{w.message}")
        if not lines:
            return "OK"
        return "\n".join(lines)


@runtime_checkable
class Validator(Protocol):
    """Common interface for shape-specific manifest validators.

    Implementations: WorkerAdapterValidator, VerticalConfigValidator, QuestionTemplateValidator.
    """

    def validate(self, manifest: dict[str, Any]) -> ValidationResult: ...
