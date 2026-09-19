"""Errors, named the same way in every Toli SDK."""

from __future__ import annotations

BODY_EXCERPT_MAX = 300


class ToliConfigError(ValueError):
    """Malformed call: missing key, inconsistent thresholds, impossible question.

    Deliberately a ValueError and NOT a ToliError: a caller catching Toli errors
    in order to retry must not silently swallow its own configuration bugs.
    """


class ToliError(Exception):
    """Root of the Toli errors.

    Carries enough to diagnose without spilling the state into a log file: the
    HTTP status, the server's request id, and a body excerpt CAPPED at 300
    characters.
    """

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        request_id: str | None = None,
        body_excerpt: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.request_id = request_id
        self.body_excerpt = body_excerpt


def excerpt(body: str) -> str:
    """Cut a response body down to what we accept to copy into a log."""
    return body[:BODY_EXCERPT_MAX]


class ToliAuthError(ToliError):
    """Key rejected (401 / 403). No retry: the same key will be rejected again."""


class ToliRateLimitError(ToliError):
    """Quota exceeded (429). The SDK already retried, honouring retry-after."""


class ToliUnavailableError(ToliError):
    """Unavailable (5xx, 529) or dropped connection. The SDK already retried."""


class ToliTimeoutError(ToliError):
    """Deadline exceeded. Transient."""


class ToliProtocolError(ToliError):
    """The server answered, but not with what was expected."""
