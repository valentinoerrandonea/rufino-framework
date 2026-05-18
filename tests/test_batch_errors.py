from rufino.engine.process.batch.errors import (
    BatchError,
    UnsupportedFormatError,
    ConversionError,
    StagingError,
    DispatchError,
    WorkerSessionExpiredError,
    ConsolidationError,
)


def test_all_errors_inherit_from_base():
    for cls in (
        UnsupportedFormatError,
        ConversionError,
        StagingError,
        DispatchError,
        WorkerSessionExpiredError,
        ConsolidationError,
    ):
        assert issubclass(cls, BatchError)
        assert issubclass(cls, Exception)


def test_errors_carry_message():
    err = UnsupportedFormatError("file.doc")
    assert "file.doc" in str(err)
