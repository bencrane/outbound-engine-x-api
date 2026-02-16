from __future__ import annotations

import random
import time
from typing import Any

import httpx


EMAILBISON_DEFAULT_API_BASE = "https://app.emailbison.com"
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
_MAX_RETRY_ATTEMPTS = 3
_RETRY_BASE_DELAY_SECONDS = 0.25
_RETRY_MAX_DELAY_SECONDS = 2.0


class EmailBisonProviderError(Exception):
    """Provider-level exception for EmailBison integration failures."""

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
            "invalid emailbison api key" in message
            or "endpoint not found" in message
            or "missing emailbison api key" in message
            or "unexpected emailbison" in message
        ):
            return "terminal"
        return "unknown"

    @property
    def retryable(self) -> bool:
        return self.category == "transient"


def _build_base_url(instance_url: str | None) -> str:
    return (instance_url or EMAILBISON_DEFAULT_API_BASE).rstrip("/")


def _request_with_retry(
    *,
    method: str,
    url: str,
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


def _headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _extract_data(payload: Any) -> Any:
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    return payload


def _request_json(
    *,
    method: str,
    candidate_paths: list[str],
    api_key: str,
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
    params: dict[str, Any] | None = None,
    json_payload: dict[str, Any] | None = None,
) -> Any:
    if not api_key:
        raise EmailBisonProviderError("Missing EmailBison API key")

    base_url = _build_base_url(instance_url)
    last_error: str | None = None

    for path in candidate_paths:
        url = f"{base_url}{path}"
        try:
            response = _request_with_retry(
                method=method,
                url=url,
                headers=_headers(api_key),
                params=params,
                json_payload=json_payload,
                timeout_seconds=timeout_seconds,
            )
        except httpx.HTTPError as exc:
            last_error = f"EmailBison connectivity error: {exc}"
            continue

        if response.status_code == 404:
            last_error = f"EmailBison endpoint not found: {path}"
            continue
        if response.status_code in {401, 403}:
            raise EmailBisonProviderError("Invalid EmailBison API key")
        if response.status_code >= 400:
            raise EmailBisonProviderError(
                f"EmailBison API returned HTTP {response.status_code}: {response.text[:200]}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise EmailBisonProviderError("EmailBison returned non-JSON response") from exc
        return _extract_data(payload)

    raise EmailBisonProviderError(last_error or "Unable to reach EmailBison API")


def validate_api_key(api_key: str, instance_url: str | None = None, timeout_seconds: float = 8.0) -> None:
    _request_json(
        method="GET",
        candidate_paths=["/api/users"],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
    )


def list_campaigns(
    api_key: str,
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> list[dict[str, Any]]:
    data = _request_json(
        method="GET",
        candidate_paths=["/api/campaigns"],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
    )
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return data["items"]
    raise EmailBisonProviderError("Unexpected EmailBison campaigns response shape")


def create_campaign(
    api_key: str,
    name: str,
    campaign_type: str = "outbound",
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    data = _request_json(
        method="POST",
        candidate_paths=["/api/campaigns"],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
        json_payload={"name": name, "type": campaign_type},
    )
    if isinstance(data, dict):
        return data
    raise EmailBisonProviderError("Unexpected EmailBison create campaign response type")


def update_campaign_status(
    api_key: str,
    campaign_id: int | str,
    status_value: str,
    instance_url: str | None = None,
    timeout_seconds: float = 10.0,
) -> dict[str, Any]:
    normalized = str(status_value).strip().upper()
    if normalized == "ACTIVE":
        candidate_paths = [f"/api/campaigns/{campaign_id}/resume"]
    elif normalized == "PAUSED":
        candidate_paths = [f"/api/campaigns/{campaign_id}/pause"]
    elif normalized in {"STOPPED", "COMPLETED"}:
        candidate_paths = [f"/api/campaigns/{campaign_id}/archive"]
    else:
        raise EmailBisonProviderError(
            f"Unsupported EmailBison campaign status transition requested: {status_value}"
        )

    data = _request_json(
        method="PATCH",
        candidate_paths=candidate_paths,
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
        json_payload=None,
    )
    if isinstance(data, dict):
        return data
    raise EmailBisonProviderError("Unexpected EmailBison campaign status response type")


def list_leads(
    api_key: str,
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> list[dict[str, Any]]:
    data = _request_json(
        method="GET",
        candidate_paths=["/api/leads"],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
    )
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return data["items"]
    raise EmailBisonProviderError("Unexpected EmailBison leads response shape")


def create_lead(
    api_key: str,
    lead: dict[str, Any],
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    data = _request_json(
        method="POST",
        candidate_paths=["/api/leads"],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
        json_payload=lead,
    )
    if isinstance(data, dict):
        return data
    raise EmailBisonProviderError("Unexpected EmailBison create lead response type")


def list_campaign_leads(
    api_key: str,
    campaign_id: int | str,
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> list[dict[str, Any]]:
    data = _request_json(
        method="GET",
        candidate_paths=[f"/api/campaigns/{campaign_id}/leads"],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
    )
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return data["items"]
    raise EmailBisonProviderError("Unexpected EmailBison campaign leads response shape")


def attach_leads_to_campaign(
    api_key: str,
    campaign_id: int | str,
    lead_ids: list[int],
    allow_parallel_sending: bool = False,
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    data = _request_json(
        method="POST",
        candidate_paths=[f"/api/campaigns/{campaign_id}/leads/attach-leads"],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
        json_payload={
            "lead_ids": lead_ids,
            "allow_parallel_sending": allow_parallel_sending,
        },
    )
    if isinstance(data, dict):
        return data
    raise EmailBisonProviderError("Unexpected EmailBison attach-leads response type")


def stop_future_emails_for_leads(
    api_key: str,
    campaign_id: int | str,
    lead_ids: list[int],
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    data = _request_json(
        method="POST",
        candidate_paths=[f"/api/campaigns/{campaign_id}/leads/stop-future-emails"],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
        json_payload={"lead_ids": lead_ids},
    )
    if isinstance(data, dict):
        return data
    raise EmailBisonProviderError("Unexpected EmailBison stop-future-emails response type")


def list_replies(
    api_key: str,
    campaign_id: int | str | None = None,
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> list[dict[str, Any]]:
    params: dict[str, Any] | None = None
    if campaign_id is not None:
        params = {"campaign_id": campaign_id}
    data = _request_json(
        method="GET",
        candidate_paths=["/api/replies"],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
        params=params,
    )
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return data["items"]
    raise EmailBisonProviderError("Unexpected EmailBison replies response shape")


def get_campaign_stats(
    api_key: str,
    campaign_id: int | str,
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    data = _request_json(
        method="GET",
        candidate_paths=[f"/api/campaigns/{campaign_id}/stats"],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
    )
    if isinstance(data, dict):
        return data
    raise EmailBisonProviderError("Unexpected EmailBison campaign stats response type")


def list_sender_emails(
    api_key: str,
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> list[dict[str, Any]]:
    data = _request_json(
        method="GET",
        candidate_paths=["/api/sender-emails"],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
    )
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return data["items"]
    raise EmailBisonProviderError("Unexpected EmailBison sender-emails response shape")


def webhook_resource_paths(webhook_id: int | str) -> dict[str, str]:
    """
    Build known webhook resource path variants from current spec outputs.

    Current spec is inconsistent across operations (`{id}` vs `{webhook_url_id}`).
    Internal callers should provide a single `webhook_id`; this helper returns
    canonical and alias variants for tolerant operation routing.
    """
    normalized = str(webhook_id)
    base_path = f"/api/webhook-url/{normalized}"
    return {
        "read_update_canonical": base_path,
        "delete_canonical": base_path,
        "delete_alias_trailing_slash": f"{base_path}/",
    }


def delete_webhook(
    api_key: str,
    webhook_id: int | str,
    instance_url: str | None = None,
    timeout_seconds: float = 10.0,
) -> dict[str, Any]:
    paths = webhook_resource_paths(webhook_id)
    data = _request_json(
        method="DELETE",
        candidate_paths=[paths["delete_canonical"], paths["delete_alias_trailing_slash"]],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
    )
    if isinstance(data, dict):
        return data
    raise EmailBisonProviderError("Unexpected EmailBison webhook delete response type")
