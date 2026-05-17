import re
from typing import Any
from rufino.runtime.validator_base import (
    ValidationResult,
    ValidationError,
    ValidationWarning,
)


_KEBAB_RE = re.compile(r"^[a-z][a-z0-9-]*$")


class VerticalConfigValidator:
    """Validates manifests for Memory loop adapters (vertical config shape)."""

    def validate(self, manifest: dict[str, Any]) -> ValidationResult:
        result = ValidationResult()

        name = manifest.get("adapter_name", "")
        if not _KEBAB_RE.match(name):
            result.errors.append(ValidationError(
                field="adapter_name",
                message=f"must be kebab-case (lowercase, hyphens), got {name!r}",
            ))

        entities = set(manifest.get("entity_types", []))
        destinations = manifest.get("note_destinations", {})

        for entity in destinations:
            if entity not in entities:
                result.warnings.append(ValidationWarning(
                    field="note_destinations",
                    message=f"references entity {entity!r} not declared in entity_types",
                ))

        for entity in entities:
            if entity not in destinations:
                result.warnings.append(ValidationWarning(
                    field="entity_types",
                    message=f"entity {entity!r} has no entry in note_destinations",
                ))

        return result
