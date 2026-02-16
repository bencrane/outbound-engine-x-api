from __future__ import annotations

from typing import Any, Protocol


class ProviderErrorLike(Protocol):
    @property
    def category(self) -> str: ...

    @property
    def retryable(self) -> bool: ...


def provider_error_http_status(exc: ProviderErrorLike) -> int:
    return 503 if exc.retryable else 502


def provider_error_detail(*, provider: str, operation: str, exc: ProviderErrorLike) -> dict[str, Any]:
    return {
        "type": "provider_error",
        "provider": provider,
        "operation": operation,
        "category": exc.category,
        "retryable": exc.retryable,
        "message": str(exc),
    }
