class BatchError(Exception):
    """Base error for the process-batch pipeline."""


class UnsupportedFormatError(BatchError):
    """Raised when an input file's extension is not supported in v0.1.0."""


class ConversionError(BatchError):
    """Raised when docx/pptx → markdown conversion fails."""


class StagingError(BatchError):
    """Raised when staging a corpus fails irrecoverably (bad ZIP, etc.)."""


class DispatchError(BatchError):
    """Raised when worker dispatch hits an unrecoverable condition."""


class WorkerSessionExpiredError(DispatchError):
    """Raised when `claude` reports an expired session — aborts the run."""


class ConsolidationError(BatchError):
    """Raised when the consolidator output is unusable (bad schema, etc.)."""
