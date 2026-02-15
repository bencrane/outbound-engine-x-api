from __future__ import annotations

from typing import Any

import httpx


HEYREACH_API_BASE = "https://api.heyreach.io/api/public"


class HeyReachProviderError(Exception):
    """Provider-level exception for HeyReach integration failures."""


def _headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "X-API-KEY": api_key,
        "Content-Type": "application/json",
    }


def _request_json(
    method: str,
    candidate_paths: list[str],
    api_key: str,
    json_payload: dict[str, Any] | None = None,
    timeout_seconds: float = 12.0,
) -> Any:
    if not api_key:
        raise HeyReachProviderError("Missing HeyReach API key")

    last_error: str | None = None
    for path in candidate_paths:
        url = f"{HEYREACH_API_BASE}{path}"
        try:
            with httpx.Client(timeout=timeout_seconds) as client:
                response = client.request(
                    method=method,
                    url=url,
                    headers=_headers(api_key),
                    json=json_payload,
                )
        except httpx.HTTPError as exc:
            last_error = f"HeyReach connectivity error: {exc}"
            continue

        if response.status_code == 404:
            last_error = f"HeyReach endpoint not found: {path}"
            continue
        if response.status_code in {401, 403}:
            raise HeyReachProviderError("Invalid HeyReach API key")
        if response.status_code >= 400:
            raise HeyReachProviderError(
                f"HeyReach API returned HTTP {response.status_code}: {response.text[:200]}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise HeyReachProviderError("HeyReach returned non-JSON response") from exc
        if isinstance(payload, dict) and "data" in payload:
            return payload["data"]
        return payload

    raise HeyReachProviderError(last_error or "Unable to reach HeyReach API")


def validate_api_key(api_key: str, timeout_seconds: float = 8.0) -> None:
    _request_json(
        method="GET",
        candidate_paths=["/campaign/GetAll", "/campaigns"],
        api_key=api_key,
        timeout_seconds=timeout_seconds,
    )


def create_campaign(
    api_key: str,
    name: str,
    description: str | None = None,
    daily_limit: int | None = None,
    delay_between_actions: int | None = None,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"name": name}
    if description:
        payload["description"] = description
    if daily_limit is not None:
        payload["dailyLimit"] = daily_limit
    if delay_between_actions is not None:
        payload["delayBetweenActions"] = delay_between_actions
    data = _request_json(
        method="POST",
        candidate_paths=["/campaign/Create", "/campaigns"],
        api_key=api_key,
        json_payload=payload,
        timeout_seconds=timeout_seconds,
    )
    if not isinstance(data, dict):
        raise HeyReachProviderError("Unexpected HeyReach create campaign response type")
    return data


def list_campaigns(api_key: str, timeout_seconds: float = 12.0) -> list[dict[str, Any]]:
    data = _request_json(
        method="GET",
        candidate_paths=["/campaign/GetAll", "/campaigns"],
        api_key=api_key,
        timeout_seconds=timeout_seconds,
    )
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return data["items"]
    raise HeyReachProviderError("Unexpected HeyReach list campaigns response shape")


def pause_campaign(api_key: str, campaign_id: str | int, timeout_seconds: float = 10.0) -> dict[str, Any]:
    data = _request_json(
        method="POST",
        candidate_paths=["/campaign/Pause", "/campaign/pause"],
        api_key=api_key,
        json_payload={"campaignId": str(campaign_id)},
        timeout_seconds=timeout_seconds,
    )
    if not isinstance(data, dict):
        raise HeyReachProviderError("Unexpected HeyReach pause campaign response type")
    return data


def resume_campaign(api_key: str, campaign_id: str | int, timeout_seconds: float = 10.0) -> dict[str, Any]:
    data = _request_json(
        method="POST",
        candidate_paths=["/campaign/Resume", "/campaign/resume"],
        api_key=api_key,
        json_payload={"campaignId": str(campaign_id)},
        timeout_seconds=timeout_seconds,
    )
    if not isinstance(data, dict):
        raise HeyReachProviderError("Unexpected HeyReach resume campaign response type")
    return data


def add_campaign_leads(
    api_key: str,
    campaign_id: str | int,
    leads: list[dict[str, Any]],
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    data = _request_json(
        method="POST",
        candidate_paths=["/campaign/AddLeadsToListV2", "/campaign/add-leads"],
        api_key=api_key,
        json_payload={"campaignId": str(campaign_id), "leads": leads},
        timeout_seconds=timeout_seconds,
    )
    if not isinstance(data, dict):
        raise HeyReachProviderError("Unexpected HeyReach add leads response type")
    return data


def get_campaign_leads(
    api_key: str,
    campaign_id: str | int,
    page: int = 1,
    limit: int = 50,
    timeout_seconds: float = 12.0,
) -> list[dict[str, Any]]:
    data = _request_json(
        method="POST",
        candidate_paths=["/campaign/GetLeads", "/campaign/leads"],
        api_key=api_key,
        json_payload={"campaignId": str(campaign_id), "page": page, "limit": limit},
        timeout_seconds=timeout_seconds,
    )
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return data["items"]
    raise HeyReachProviderError("Unexpected HeyReach campaign leads response shape")


def update_lead_status(
    api_key: str,
    lead_id: str | int,
    status_value: str,
    timeout_seconds: float = 10.0,
) -> dict[str, Any]:
    data = _request_json(
        method="POST",
        candidate_paths=["/lead/UpdateStatus", "/lead/update-status"],
        api_key=api_key,
        json_payload={"leadId": str(lead_id), "status": status_value},
        timeout_seconds=timeout_seconds,
    )
    if not isinstance(data, dict):
        raise HeyReachProviderError("Unexpected HeyReach lead status response type")
    return data


def send_message(
    api_key: str,
    lead_id: str | int,
    message: str,
    template_id: str | None = None,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"leadId": str(lead_id), "message": message}
    if template_id:
        payload["templateId"] = template_id
    data = _request_json(
        method="POST",
        candidate_paths=["/message/Send", "/message/send"],
        api_key=api_key,
        json_payload=payload,
        timeout_seconds=timeout_seconds,
    )
    if not isinstance(data, dict):
        raise HeyReachProviderError("Unexpected HeyReach send message response type")
    return data


def get_campaign_metrics(api_key: str, campaign_id: str | int, timeout_seconds: float = 12.0) -> dict[str, Any]:
    data = _request_json(
        method="GET",
        candidate_paths=[
            f"/analytics/campaign/{campaign_id}",
            f"/campaign/{campaign_id}/metrics",
        ],
        api_key=api_key,
        timeout_seconds=timeout_seconds,
    )
    if not isinstance(data, dict):
        raise HeyReachProviderError("Unexpected HeyReach metrics response type")
    return data
