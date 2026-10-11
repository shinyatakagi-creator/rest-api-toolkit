"""Typed errors, so a caller can tell a bad token from a bad payload from a bad day at the provider."""
from __future__ import annotations


class ApiError(Exception):
    """Base class. Carries what you need to write a useful support ticket."""

    def __init__(self, message: str, *, status: int | None = None, body: str = "",
                 request_id: str | None = None, url: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.body = body
        self.request_id = request_id
        self.url = url

    def __str__(self) -> str:
        parts = [super().__str__()]
        if self.status is not None:
            parts.append(f"status={self.status}")
        if self.request_id:
            parts.append(f"request_id={self.request_id}")
        if self.url:
            parts.append(f"url={self.url}")
        return " | ".join(parts)


class BadRequestError(ApiError):
    """400 or 422. The request is wrong. Retrying will not help."""


class AuthenticationError(ApiError):
    """401. Missing, expired or invalid credentials."""


class ForbiddenError(ApiError):
    """403. Credentials are valid but not allowed to do this."""


class NotFoundError(ApiError):
    """404. Wrong path, wrong id, or no access (some APIs hide resources as 404)."""


class ConflictError(ApiError):
    """409. State conflict, often a duplicate create or a stale update."""


class RateLimitError(ApiError):
    """429. Too many requests. Carries retry_after in seconds when the server sent it."""

    def __init__(self, *args, retry_after: float | None = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.retry_after = retry_after


class ServerError(ApiError):
    """5xx. The provider has a problem. Often worth retrying, then escalating."""
