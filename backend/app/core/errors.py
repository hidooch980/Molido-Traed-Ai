"""Domain errors.

`InsufficientDataError` is deliberately a first-class error: the spec forbids
inventing statistics when the data does not support them. Callers must handle
"we don't know" explicitly rather than receiving a plausible-looking number.
"""

from __future__ import annotations


class MolidoError(Exception):
    """Base class for all domain errors."""

    code = "molido_error"
    http_status = 500

    def __init__(self, message: str, **context: object) -> None:
        super().__init__(message)
        self.message = message
        self.context = context

    def to_payload(self) -> dict[str, object]:
        return {"error": self.code, "message": self.message, "context": self.context}


class ConfigurationError(MolidoError):
    code = "configuration_error"


class ProviderError(MolidoError):
    """A market-data provider failed or returned unusable data."""

    code = "provider_error"
    http_status = 502


class RateLimitedError(ProviderError):
    code = "rate_limited"
    http_status = 429

    def __init__(self, message: str, retry_after_seconds: float | None = None, **ctx: object):
        super().__init__(message, retry_after_seconds=retry_after_seconds, **ctx)
        self.retry_after_seconds = retry_after_seconds


class ValidationFailedError(MolidoError):
    code = "validation_failed"
    http_status = 422


class InsufficientDataError(MolidoError):
    """Not enough trustworthy data to answer. Never substitute an estimate."""

    code = "insufficient_data"
    http_status = 409


class LookaheadViolationError(MolidoError):
    """A read attempted to see information from after its as-of timestamp."""

    code = "lookahead_violation"
    http_status = 500


class TenantIsolationError(MolidoError):
    code = "tenant_isolation_violation"
    http_status = 403


class NotFoundError(MolidoError):
    code = "not_found"
    http_status = 404


class ConflictError(MolidoError):
    """The request is well-formed but the world is already in a state that
    refuses it - an address that is taken, a deployment already claimed.

    409 rather than 422: nothing about the request is malformed, so retrying it
    unchanged after the conflict clears is the correct thing for a caller to
    do, and 422 tells them the opposite.
    """

    code = "conflict"
    http_status = 409


class SafeModeError(MolidoError):
    """The system is in safe mode and refuses risk-increasing actions."""

    code = "safe_mode"
    http_status = 503
