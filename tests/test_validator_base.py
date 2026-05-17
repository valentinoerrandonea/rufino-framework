import pytest
from rufino.runtime.validator_base import (
    Validator,
    ValidationError,
    ValidationWarning,
    ValidationResult,
)


def test_validation_result_ok_when_no_issues():
    result = ValidationResult(errors=[], warnings=[])
    assert result.ok is True


def test_validation_result_not_ok_with_errors():
    result = ValidationResult(
        errors=[ValidationError(field="name", message="required", line=12)],
        warnings=[],
    )
    assert result.ok is False


def test_validation_result_ok_with_only_warnings():
    result = ValidationResult(
        errors=[],
        warnings=[ValidationWarning(field="qa_triggers", message="empty", line=20)],
    )
    assert result.ok is True


def test_validator_protocol_minimal():
    class NoopValidator:
        def validate(self, manifest: dict) -> ValidationResult:
            return ValidationResult(errors=[], warnings=[])

    v: Validator = NoopValidator()
    assert v.validate({}).ok
