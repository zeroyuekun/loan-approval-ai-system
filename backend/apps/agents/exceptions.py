"""Custom exception hierarchy for the agents pipeline.

These exceptions allow catch blocks to distinguish between expected failure
modes (e.g. rate limits, model not found) and truly unexpected errors, so
that logging, retry logic, and failure categorisation are precise.
"""

from enum import StrEnum


class FailureCategory(StrEnum):
    """Classifies pipeline step failures for monitoring and retry decisions."""

    TRANSIENT = "transient"
    PERMANENT = "permanent"
    INFRASTRUCTURE = "infrastructure"
    UNKNOWN = "unknown"


class PipelineError(Exception):
    """Base for all pipeline errors."""

    pass


class PipelineStepError(PipelineError):
    """A named pipeline step failed."""

    def __init__(
        self, step_name: str, message: str, retryable: bool = False, category: "FailureCategory | None" = None
    ):
        self.step_name = step_name
        self.retryable = retryable
        self.category = category
        super().__init__(message)


class ExternalServiceError(PipelineError):
    """An external service (API, database, etc.) failed."""

    pass


class LLMServiceError(ExternalServiceError):
    """Any LLM API call failure."""

    pass


class LLMRateLimitError(LLMServiceError):
    """Claude API rate limit (429)."""

    pass


class LLMAuthError(LLMServiceError):
    """Claude API authentication failure (401/403)."""

    pass


class LLMTimeoutError(LLMServiceError):
    """Claude API timeout."""

    pass


class MLPredictionError(PipelineError):
    """ML model prediction failed."""

    pass


class ModelNotFoundError(MLPredictionError):
    """No active model version found."""

    pass


class ApplicationNotFoundError(PipelineError):
    """Loan application not found."""

    pass


class InvalidApplicationStateError(PipelineError):
    """Application is in an unexpected state for the requested operation."""

    pass
