"""Shared exceptions for the external-service wrappers (STT, LLM, TTS)."""
from typing import Optional


class ServiceError(Exception):
    retryable = False

    def __init__(self, service: str, message: str, status_code: Optional[int] = None):
        suffix = f" (HTTP {status_code})" if status_code else ""
        super().__init__(f"[{service}] {message}{suffix}")
        self.service = service
        self.message = message
        self.status_code = status_code


class ServiceTimeout(ServiceError):
    retryable = True


class ServiceUnavailable(ServiceError):
    """Network error, 429 rate limit, or 5xx."""

    retryable = True


class ServiceAuthError(ServiceError):
    """401 / 402 / 403: bad key, no credits, missing scope."""


class ServiceBadRequest(ServiceError):
    """400 / 422: bad audio, bad parameters."""
