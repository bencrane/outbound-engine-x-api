from __future__ import annotations

import random
import time
from typing import Any

import httpx


LOB_API_BASE = "https://api.lob.com"
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
_MAX_RETRY_ATTEMPTS = 3
_RETRY_BASE_DELAY_SECONDS = 0.25
_RETRY_MAX_DELAY_SECONDS = 2.0

_EP_US_VERIFICATIONS = "/v1/us_verifications"
_EP_US_BULK_VERIFICATIONS = "/v1/bulk/us_verifications"
_EP_POSTCARDS = "/v1/postcards"
_EP_LETTERS = "/v1/letters"


class LobProviderError(Exception):
    """Provider-level exception for Lob integration failures."""

    @property
    def category(self) -> str:
        message = str(self).lower()
        if (
            "connectivity error" in message
            or "http 429" in message
            or "http 500" in message
            or "http 502" in message
            or "http 503" in message
            or "http 504" in message
        ):
            return "transient"
        if (
            "invalid lob api key" in message
            or "endpoint not found" in message
            or "missing lob api key" in message
            or "cannot send both header and query idempotency keys" in message
            or "unexpected lob" in message
        ):
            return "terminal"
        return "unknown"

    @property
    def retryable(self) -> bool:
        return self.category == "transient"


def _build_base_url(base_url: str | None) -> str:
    return (base_url or LOB_API_BASE).rstrip("/")


def _build_basic_auth(api_key: str) -> tuple[str, str]:
    return (api_key, "")


def _request_with_retry(
    *,
    method: str,
    url: str,
    auth: tuple[str, str],
    headers: dict[str, str],
    timeout_seconds: float,
    params: dict[str, Any] | None = None,
    json_payload: dict[str, Any] | None = None,
) -> httpx.Response:
    last_exc: httpx.HTTPError | None = None
    response: httpx.Response | None = None
    for attempt in range(1, _MAX_RETRY_ATTEMPTS + 1):
        try:
            with httpx.Client(timeout=timeout_seconds) as client:
                response = client.request(
                    method=method,
                    url=url,
                    auth=auth,
                    headers=headers,
                    params=params,
                    json=json_payload,
                )
        except httpx.HTTPError as exc:
            last_exc = exc
            if attempt >= _MAX_RETRY_ATTEMPTS:
                raise
            delay = min(_RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1)), _RETRY_MAX_DELAY_SECONDS)
            delay += random.uniform(0, delay * 0.2)
            time.sleep(delay)
            continue

        if response.status_code in _RETRYABLE_STATUS_CODES and attempt < _MAX_RETRY_ATTEMPTS:
            delay = min(_RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1)), _RETRY_MAX_DELAY_SECONDS)
            delay += random.uniform(0, delay * 0.2)
            time.sleep(delay)
            continue
        return response

    if last_exc:
        raise last_exc
    assert response is not None
    return response


def build_idempotency_material(
    *,
    header_key: str | None = None,
    query_key: str | None = None,
) -> tuple[dict[str, str], dict[str, str]]:
    if header_key and query_key:
        raise LobProviderError("Cannot send both header and query idempotency keys")

    headers: dict[str, str] = {}
    query: dict[str, str] = {}
    if header_key:
        headers["Idempotency-Key"] = header_key
    if query_key:
        query["idempotency_key"] = query_key
    return headers, query


def _request_json(
    *,
    method: str,
    path: str,
    api_key: str,
    base_url: str | None = None,
    timeout_seconds: float = 12.0,
    params: dict[str, Any] | None = None,
    json_payload: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
    idempotency_in_query: bool = False,
) -> Any:
    if not api_key:
        raise LobProviderError("Missing Lob API key")

    normalized_key = idempotency_key.strip() if isinstance(idempotency_key, str) else idempotency_key
    if normalized_key == "":
        raise LobProviderError("Idempotency key must be non-empty when provided")

    idempotency_headers, idempotency_query = build_idempotency_material(
        header_key=(normalized_key if normalized_key and not idempotency_in_query else None),
        query_key=(normalized_key if normalized_key and idempotency_in_query else None),
    )

    request_headers = {"Accept": "application/json", "Content-Type": "application/json"}
    request_headers.update(idempotency_headers)

    request_params = dict(params or {})
    request_params.update(idempotency_query)

    url = f"{_build_base_url(base_url)}{path}"
    try:
        response = _request_with_retry(
            method=method,
            url=url,
            auth=_build_basic_auth(api_key),
            headers=request_headers,
            timeout_seconds=timeout_seconds,
            params=request_params or None,
            json_payload=json_payload,
        )
    except httpx.HTTPError as exc:
        raise LobProviderError(f"Lob connectivity error: {exc}") from exc

    if response.status_code in {401, 403}:
        raise LobProviderError("Invalid Lob API key")
    if response.status_code == 404:
        raise LobProviderError(f"Lob endpoint not found: {path}")
    if response.status_code >= 400:
        raise LobProviderError(f"Lob API returned HTTP {response.status_code}: {response.text[:200]}")

    try:
        return response.json()
    except ValueError as exc:
        raise LobProviderError("Lob returned non-JSON response") from exc


def validate_api_key(
    api_key: str,
    base_url: str | None = None,
    timeout_seconds: float = 8.0,
) -> None:
    _request_json(
        method="GET",
        path=_EP_POSTCARDS,
        api_key=api_key,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
        params={"limit": 1},
    )


def verify_address_us_single(
    api_key: str,
    payload: dict[str, Any],
    base_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    data = _request_json(
        method="POST",
        path=_EP_US_VERIFICATIONS,
        api_key=api_key,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
        json_payload=payload,
    )
    if not isinstance(data, dict):
        raise LobProviderError("Unexpected Lob US verification response type")
    return data


def verify_address_us_bulk(
    api_key: str,
    payload: dict[str, Any],
    base_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    data = _request_json(
        method="POST",
        path=_EP_US_BULK_VERIFICATIONS,
        api_key=api_key,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
        json_payload=payload,
    )
    if not isinstance(data, dict):
        raise LobProviderError("Unexpected Lob bulk US verification response type")
    return data


def create_postcard(
    api_key: str,
    payload: dict[str, Any],
    *,
    idempotency_key: str | None = None,
    idempotency_in_query: bool = False,
    base_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    data = _request_json(
        method="POST",
        path=_EP_POSTCARDS,
        api_key=api_key,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
        json_payload=payload,
        idempotency_key=idempotency_key,
        idempotency_in_query=idempotency_in_query,
    )
    if not isinstance(data, dict):
        raise LobProviderError("Unexpected Lob create postcard response type")
    return data


def list_postcards(
    api_key: str,
    *,
    params: dict[str, Any] | None = None,
    base_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    data = _request_json(
        method="GET",
        path=_EP_POSTCARDS,
        api_key=api_key,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
        params=params,
    )
    if not isinstance(data, dict):
        raise LobProviderError("Unexpected Lob list postcards response type")
    return data


def get_postcard(
    api_key: str,
    postcard_id: str,
    *,
    base_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    data = _request_json(
        method="GET",
        path=f"{_EP_POSTCARDS}/{postcard_id}",
        api_key=api_key,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
    )
    if not isinstance(data, dict):
        raise LobProviderError("Unexpected Lob get postcard response type")
    return data


def cancel_postcard(
    api_key: str,
    postcard_id: str,
    *,
    idempotency_key: str | None = None,
    idempotency_in_query: bool = False,
    base_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    data = _request_json(
        method="DELETE",
        path=f"{_EP_POSTCARDS}/{postcard_id}",
        api_key=api_key,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
        idempotency_key=idempotency_key,
        idempotency_in_query=idempotency_in_query,
    )
    if not isinstance(data, dict):
        raise LobProviderError("Unexpected Lob cancel postcard response type")
    return data


def create_letter(
    api_key: str,
    payload: dict[str, Any],
    *,
    idempotency_key: str | None = None,
    idempotency_in_query: bool = False,
    base_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    data = _request_json(
        method="POST",
        path=_EP_LETTERS,
        api_key=api_key,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
        json_payload=payload,
        idempotency_key=idempotency_key,
        idempotency_in_query=idempotency_in_query,
    )
    if not isinstance(data, dict):
        raise LobProviderError("Unexpected Lob create letter response type")
    return data


def list_letters(
    api_key: str,
    *,
    params: dict[str, Any] | None = None,
    base_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    data = _request_json(
        method="GET",
        path=_EP_LETTERS,
        api_key=api_key,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
        params=params,
    )
    if not isinstance(data, dict):
        raise LobProviderError("Unexpected Lob list letters response type")
    return data


def get_letter(
    api_key: str,
    letter_id: str,
    *,
    base_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    data = _request_json(
        method="GET",
        path=f"{_EP_LETTERS}/{letter_id}",
        api_key=api_key,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
    )
    if not isinstance(data, dict):
        raise LobProviderError("Unexpected Lob get letter response type")
    return data


def cancel_letter(
    api_key: str,
    letter_id: str,
    *,
    idempotency_key: str | None = None,
    idempotency_in_query: bool = False,
    base_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    data = _request_json(
        method="DELETE",
        path=f"{_EP_LETTERS}/{letter_id}",
        api_key=api_key,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
        idempotency_key=idempotency_key,
        idempotency_in_query=idempotency_in_query,
    )
    if not isinstance(data, dict):
        raise LobProviderError("Unexpected Lob cancel letter response type")
    return data


LOB_IMPLEMENTED_ENDPOINT_REGISTRY: dict[str, list[dict[str, str]]] = {
    "validate_api_key": [{"method": "GET", "path": _EP_POSTCARDS}],
    "verify_address_us_single": [{"method": "POST", "path": _EP_US_VERIFICATIONS}],
    "verify_address_us_bulk": [{"method": "POST", "path": _EP_US_BULK_VERIFICATIONS}],
    "create_postcard": [{"method": "POST", "path": _EP_POSTCARDS}],
    "list_postcards": [{"method": "GET", "path": _EP_POSTCARDS}],
    "get_postcard": [{"method": "GET", "path": "/v1/postcards/{psc_id}"}],
    "cancel_postcard": [{"method": "DELETE", "path": "/v1/postcards/{psc_id}"}],
    "create_letter": [{"method": "POST", "path": _EP_LETTERS}],
    "list_letters": [{"method": "GET", "path": _EP_LETTERS}],
    "get_letter": [{"method": "GET", "path": "/v1/letters/{ltr_id}"}],
    "cancel_letter": [{"method": "DELETE", "path": "/v1/letters/{ltr_id}"}],
}


LOB_CONTRACT_STATUS_REGISTRY: dict[str, dict[str, str]] = {
    "lob.webhooks.signature_contract": {
        "status": "blocked_contract_missing",
        "evidence": "Missing canonical signing header, algorithm, payload canonicalization, and replay/timestamp contract details in current docs extraction.",
    },
    "lob.idempotency.write_contract": {
        "status": "deferred",
        "evidence": "Idempotency is documented: use either `Idempotency-Key` header or `idempotency_key` query param, key retention is 24 hours, never both simultaneously.",
    },
    "lob.self_mailers.workflow": {
        "status": "deferred",
        "evidence": "Deferred from v1 operator-grade MVP scope.",
    },
    "lob.checks.workflow": {
        "status": "deferred",
        "evidence": "Deferred from v1 operator-grade MVP scope.",
    },
}
