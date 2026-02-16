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

_EP_USERS = "/api/users"
_EP_CAMPAIGNS = "/api/campaigns"
_EP_LEADS = "/api/leads"
_EP_REPLIES = "/api/replies"
_EP_SENDER_EMAILS = "/api/sender-emails"
_EP_WARMUP_SENDER_EMAILS = "/api/warmup/sender-emails"
_EP_TAGS = "/api/tags"
_EP_CUSTOM_VARIABLES = "/api/custom-variables"
_EP_BLACKLISTED_EMAILS = "/api/blacklisted-emails"
_EP_BLACKLISTED_DOMAINS = "/api/blacklisted-domains"
_EP_WORKSPACE_STATS = "/api/workspaces/v1.1/stats"
_EP_MASTER_INBOX_SETTINGS = "/api/workspaces/v1.1/master-inbox-settings"
_EP_CAMPAIGN_EVENTS_STATS = "/api/campaign-events/stats"


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
        candidate_paths=[_EP_USERS],
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
        candidate_paths=[_EP_CAMPAIGNS],
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
        candidate_paths=[_EP_CAMPAIGNS],
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


def get_campaign_sequence_steps(
    api_key: str,
    campaign_id: int | str,
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> list[dict[str, Any]]:
    data = _request_json(
        method="GET",
        candidate_paths=[f"/api/campaigns/{campaign_id}/sequence-steps"],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
    )
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return data["items"]
    raise EmailBisonProviderError("Unexpected EmailBison campaign sequence steps response shape")


def create_campaign_sequence_steps(
    api_key: str,
    campaign_id: int | str,
    title: str,
    sequence_steps: list[dict[str, Any]],
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    data = _request_json(
        method="POST",
        candidate_paths=[f"/api/campaigns/{campaign_id}/sequence-steps"],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
        json_payload={"title": title, "sequence_steps": sequence_steps},
    )
    if isinstance(data, dict):
        return data
    raise EmailBisonProviderError("Unexpected EmailBison create sequence steps response type")


def get_campaign_schedule(
    api_key: str,
    campaign_id: int | str,
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    data = _request_json(
        method="GET",
        candidate_paths=[f"/api/campaigns/{campaign_id}/schedule"],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
    )
    if isinstance(data, dict):
        return data
    raise EmailBisonProviderError("Unexpected EmailBison campaign schedule response type")


def create_campaign_schedule(
    api_key: str,
    campaign_id: int | str,
    schedule: dict[str, Any],
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    data = _request_json(
        method="POST",
        candidate_paths=[f"/api/campaigns/{campaign_id}/schedule"],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
        json_payload=schedule,
    )
    if isinstance(data, dict):
        return data
    raise EmailBisonProviderError("Unexpected EmailBison create campaign schedule response type")


def get_campaign_sending_schedule(
    api_key: str,
    campaign_id: int | str,
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> list[dict[str, Any]]:
    data = _request_json(
        method="GET",
        candidate_paths=[f"/api/campaigns/{campaign_id}/sending-schedule"],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
    )
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return data["items"]
    raise EmailBisonProviderError("Unexpected EmailBison campaign sending schedule response shape")


def get_campaign_sender_emails(
    api_key: str,
    campaign_id: int | str,
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> list[dict[str, Any]]:
    data = _request_json(
        method="GET",
        candidate_paths=[f"/api/campaigns/{campaign_id}/sender-emails"],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
    )
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return data["items"]
    raise EmailBisonProviderError("Unexpected EmailBison campaign sender emails response shape")


def get_campaign_line_area_chart_stats(
    api_key: str,
    campaign_id: int | str,
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> list[dict[str, Any]]:
    data = _request_json(
        method="GET",
        candidate_paths=[f"/api/campaigns/{campaign_id}/line-area-chart-stats"],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
    )
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return data["items"]
    raise EmailBisonProviderError("Unexpected EmailBison line-area-chart stats response shape")


def list_leads(
    api_key: str,
    search: str | None = None,
    filters: dict[str, Any] | None = None,
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {}
    if search:
        params["search"] = search
    if filters:
        for key, value in filters.items():
            params[f"filters.{key}"] = value
    data = _request_json(
        method="GET",
        candidate_paths=[_EP_LEADS],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
        params=params or None,
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
        candidate_paths=[_EP_LEADS],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
        json_payload=lead,
    )
    if isinstance(data, dict):
        return data
    raise EmailBisonProviderError("Unexpected EmailBison create lead response type")


def create_leads_bulk(
    api_key: str,
    leads: list[dict[str, Any]],
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> list[dict[str, Any]]:
    data = _request_json(
        method="POST",
        candidate_paths=[f"{_EP_LEADS}/multiple"],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
        json_payload={"leads": leads},
    )
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return data["items"]
    raise EmailBisonProviderError("Unexpected EmailBison bulk create leads response shape")


def create_or_update_leads_bulk(
    api_key: str,
    leads: list[dict[str, Any]],
    existing_lead_behavior: str = "patch",
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> list[dict[str, Any]]:
    payload = {"leads": leads, "existing_lead_behavior": existing_lead_behavior}
    data = _request_json(
        method="POST",
        candidate_paths=[f"{_EP_LEADS}/create-or-update/multiple"],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
        json_payload=payload,
    )
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return data["items"]
    raise EmailBisonProviderError("Unexpected EmailBison bulk upsert leads response shape")


def get_lead(
    api_key: str,
    lead_id: int | str,
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    data = _request_json(
        method="GET",
        candidate_paths=[f"{_EP_LEADS}/{lead_id}"],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
    )
    if isinstance(data, dict):
        return data
    raise EmailBisonProviderError("Unexpected EmailBison get lead response type")


def update_lead(
    api_key: str,
    lead_id: int | str,
    lead: dict[str, Any],
    replace_all: bool = False,
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    data = _request_json(
        method="PUT" if replace_all else "PATCH",
        candidate_paths=[f"{_EP_LEADS}/{lead_id}"],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
        json_payload=lead,
    )
    if isinstance(data, dict):
        return data
    raise EmailBisonProviderError("Unexpected EmailBison update lead response type")


def update_lead_status(
    api_key: str,
    lead_id: int | str,
    status_value: str,
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    data = _request_json(
        method="PATCH",
        candidate_paths=[f"{_EP_LEADS}/{lead_id}/update-status"],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
        json_payload={"status": status_value},
    )
    if isinstance(data, dict):
        return data
    raise EmailBisonProviderError("Unexpected EmailBison update lead status response type")


def unsubscribe_lead(
    api_key: str,
    lead_id: int | str,
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    data = _request_json(
        method="PATCH",
        candidate_paths=[f"{_EP_LEADS}/{lead_id}/unsubscribe"],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
    )
    if isinstance(data, dict):
        return data
    raise EmailBisonProviderError("Unexpected EmailBison unsubscribe lead response type")


def delete_lead(
    api_key: str,
    lead_id: int | str,
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    data = _request_json(
        method="DELETE",
        candidate_paths=[f"{_EP_LEADS}/{lead_id}"],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
    )
    if isinstance(data, dict):
        return data
    raise EmailBisonProviderError("Unexpected EmailBison delete lead response type")


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


def attach_lead_list_to_campaign(
    api_key: str,
    campaign_id: int | str,
    lead_list_id: int,
    allow_parallel_sending: bool = False,
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    data = _request_json(
        method="POST",
        candidate_paths=[f"/api/campaigns/{campaign_id}/leads/attach-lead-list"],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
        json_payload={
            "lead_list_id": lead_list_id,
            "allow_parallel_sending": allow_parallel_sending,
        },
    )
    if isinstance(data, dict):
        return data
    raise EmailBisonProviderError("Unexpected EmailBison attach-lead-list response type")


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


def remove_leads_from_campaign(
    api_key: str,
    campaign_id: int | str,
    lead_ids: list[int],
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    data = _request_json(
        method="DELETE",
        candidate_paths=[f"/api/campaigns/{campaign_id}/leads"],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
        json_payload={"lead_ids": lead_ids},
    )
    if isinstance(data, dict):
        return data
    raise EmailBisonProviderError("Unexpected EmailBison remove-leads response type")


def list_replies(
    api_key: str,
    search: str | None = None,
    status: str | None = None,
    folder: str | None = None,
    read: bool | None = None,
    campaign_id: int | str | None = None,
    sender_email_id: int | None = None,
    lead_id: int | None = None,
    tag_ids: list[int] | None = None,
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {}
    if search is not None:
        params["search"] = search
    if status is not None:
        params["status"] = status
    if folder is not None:
        params["folder"] = folder
    if read is not None:
        params["read"] = read
    if campaign_id is not None:
        params["campaign_id"] = campaign_id
    if sender_email_id is not None:
        params["sender_email_id"] = sender_email_id
    if lead_id is not None:
        params["lead_id"] = lead_id
    if tag_ids is not None:
        params["tag_ids"] = tag_ids
    data = _request_json(
        method="GET",
        candidate_paths=[_EP_REPLIES],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
        params=params or None,
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
    search: str | None = None,
    tag_ids: list[int] | None = None,
    excluded_tag_ids: list[int] | None = None,
    without_tags: bool | None = None,
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {}
    if search is not None:
        params["search"] = search
    if tag_ids is not None:
        params["tag_ids"] = tag_ids
    if excluded_tag_ids is not None:
        params["excluded_tag_ids"] = excluded_tag_ids
        params["filters.excluded_tag_ids"] = excluded_tag_ids
    if without_tags is not None:
        params["without_tags"] = without_tags
        params["filters.without_tags"] = without_tags
    data = _request_json(
        method="GET",
        candidate_paths=[_EP_SENDER_EMAILS],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
        params=params or None,
    )
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return data["items"]
    raise EmailBisonProviderError("Unexpected EmailBison sender-emails response shape")


def get_sender_email(
    api_key: str,
    sender_email_id: int | str,
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    data = _request_json(
        method="GET",
        candidate_paths=[f"{_EP_SENDER_EMAILS}/{sender_email_id}"],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
    )
    if isinstance(data, dict):
        return data
    raise EmailBisonProviderError("Unexpected EmailBison sender-email response type")


def update_sender_email(
    api_key: str,
    sender_email_id: int | str,
    updates: dict[str, Any],
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    data = _request_json(
        method="PATCH",
        candidate_paths=[f"{_EP_SENDER_EMAILS}/{sender_email_id}"],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
        json_payload=updates,
    )
    if isinstance(data, dict):
        return data
    raise EmailBisonProviderError("Unexpected EmailBison update sender-email response type")


def delete_sender_email(
    api_key: str,
    sender_email_id: int | str,
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    data = _request_json(
        method="DELETE",
        candidate_paths=[f"{_EP_SENDER_EMAILS}/{sender_email_id}"],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
    )
    if isinstance(data, dict):
        return data
    raise EmailBisonProviderError("Unexpected EmailBison delete sender-email response type")


def list_sender_emails_with_warmup_stats(
    api_key: str,
    start_date: str,
    end_date: str,
    search: str | None = None,
    tag_ids: list[int] | None = None,
    excluded_tag_ids: list[int] | None = None,
    without_tags: bool | None = None,
    warmup_status: str | None = None,
    mx_records_status: str | None = None,
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"start_date": start_date, "end_date": end_date}
    if search is not None:
        params["search"] = search
    if tag_ids is not None:
        params["tag_ids"] = tag_ids
    if excluded_tag_ids is not None:
        params["excluded_tag_ids"] = excluded_tag_ids
        params["filters.excluded_tag_ids"] = excluded_tag_ids
    if without_tags is not None:
        params["without_tags"] = without_tags
        params["filters.without_tags"] = without_tags
    if warmup_status is not None:
        params["warmup_status"] = warmup_status
    if mx_records_status is not None:
        params["mx_records_status"] = mx_records_status
    data = _request_json(
        method="GET",
        candidate_paths=[_EP_WARMUP_SENDER_EMAILS],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
        params=params,
    )
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return data["items"]
    raise EmailBisonProviderError("Unexpected EmailBison warmup sender-emails response shape")


def get_sender_email_warmup_details(
    api_key: str,
    sender_email_id: int | str,
    start_date: str,
    end_date: str,
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    data = _request_json(
        method="GET",
        candidate_paths=[f"{_EP_WARMUP_SENDER_EMAILS}/{sender_email_id}"],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
        params={"start_date": start_date, "end_date": end_date},
    )
    if isinstance(data, dict):
        return data
    raise EmailBisonProviderError("Unexpected EmailBison sender warmup details response type")


def enable_warmup_for_sender_emails(
    api_key: str,
    sender_email_ids: list[int],
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    data = _request_json(
        method="PATCH",
        candidate_paths=[f"{_EP_WARMUP_SENDER_EMAILS}/enable"],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
        json_payload={"sender_email_ids": sender_email_ids},
    )
    if isinstance(data, dict):
        return data
    raise EmailBisonProviderError("Unexpected EmailBison warmup enable response type")


def disable_warmup_for_sender_emails(
    api_key: str,
    sender_email_ids: list[int],
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    data = _request_json(
        method="PATCH",
        candidate_paths=[f"{_EP_WARMUP_SENDER_EMAILS}/disable"],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
        json_payload={"sender_email_ids": sender_email_ids},
    )
    if isinstance(data, dict):
        return data
    raise EmailBisonProviderError("Unexpected EmailBison warmup disable response type")


def update_sender_email_daily_warmup_limits(
    api_key: str,
    sender_email_ids: list[int],
    daily_limit: int,
    daily_reply_limit: int | str | None = None,
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "sender_email_ids": sender_email_ids,
        "daily_limit": daily_limit,
    }
    if daily_reply_limit is not None:
        payload["daily_reply_limit"] = daily_reply_limit
    data = _request_json(
        method="PATCH",
        candidate_paths=[f"{_EP_WARMUP_SENDER_EMAILS}/update-daily-warmup-limits"],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
        json_payload=payload,
    )
    if isinstance(data, dict):
        return data
    raise EmailBisonProviderError("Unexpected EmailBison warmup limits response type")


def check_sender_email_mx_records(
    api_key: str,
    sender_email_id: int | str,
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    data = _request_json(
        method="POST",
        candidate_paths=[f"{_EP_SENDER_EMAILS}/{sender_email_id}/check-mx-records"],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
    )
    if isinstance(data, dict):
        return data
    raise EmailBisonProviderError("Unexpected EmailBison mx-record check response type")


def bulk_check_missing_mx_records(
    api_key: str,
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    data = _request_json(
        method="POST",
        candidate_paths=[f"{_EP_SENDER_EMAILS}/bulk-check-missing-mx-records"],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
    )
    if isinstance(data, dict):
        return data
    raise EmailBisonProviderError("Unexpected EmailBison bulk mx-record check response type")


def list_tags(
    api_key: str,
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> list[dict[str, Any]]:
    data = _request_json(
        method="GET",
        candidate_paths=[_EP_TAGS],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
    )
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return data["items"]
    raise EmailBisonProviderError("Unexpected EmailBison tags response shape")


def create_tag(
    api_key: str,
    name: str,
    default: bool | None = None,
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"name": name}
    if default is not None:
        payload["default"] = default
    data = _request_json(
        method="POST",
        candidate_paths=[_EP_TAGS],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
        json_payload=payload,
    )
    if isinstance(data, dict):
        return data
    raise EmailBisonProviderError("Unexpected EmailBison create tag response type")


def get_tag(
    api_key: str,
    tag_id: int | str,
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    data = _request_json(
        method="GET",
        candidate_paths=[f"{_EP_TAGS}/{tag_id}"],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
    )
    if isinstance(data, dict):
        return data
    raise EmailBisonProviderError("Unexpected EmailBison get tag response type")


def delete_tag(
    api_key: str,
    tag_id: int | str,
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    data = _request_json(
        method="DELETE",
        candidate_paths=[f"{_EP_TAGS}/{tag_id}"],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
    )
    if isinstance(data, dict):
        return data
    raise EmailBisonProviderError("Unexpected EmailBison delete tag response type")


def attach_tags_to_leads(
    api_key: str,
    tag_ids: list[int],
    lead_ids: list[int],
    skip_webhooks: bool | None = None,
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"tag_ids": tag_ids, "lead_ids": lead_ids}
    if skip_webhooks is not None:
        payload["skip_webhooks"] = skip_webhooks
    data = _request_json(
        method="POST",
        candidate_paths=[f"{_EP_TAGS}/attach-to-leads"],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
        json_payload=payload,
    )
    if isinstance(data, dict):
        return data
    raise EmailBisonProviderError("Unexpected EmailBison attach tags to leads response type")


def remove_tags_from_leads(
    api_key: str,
    tag_ids: list[int],
    lead_ids: list[int],
    skip_webhooks: bool | None = None,
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"tag_ids": tag_ids, "lead_ids": lead_ids}
    if skip_webhooks is not None:
        payload["skip_webhooks"] = skip_webhooks
    data = _request_json(
        method="POST",
        candidate_paths=[f"{_EP_TAGS}/remove-from-leads"],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
        json_payload=payload,
    )
    if isinstance(data, dict):
        return data
    raise EmailBisonProviderError("Unexpected EmailBison remove tags from leads response type")


def attach_tags_to_campaigns(
    api_key: str,
    tag_ids: list[int],
    campaign_ids: list[int],
    skip_webhooks: bool | None = None,
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"tag_ids": tag_ids, "campaign_ids": campaign_ids}
    if skip_webhooks is not None:
        payload["skip_webhooks"] = skip_webhooks
    data = _request_json(
        method="POST",
        candidate_paths=[f"{_EP_TAGS}/attach-to-campaigns"],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
        json_payload=payload,
    )
    if isinstance(data, dict):
        return data
    raise EmailBisonProviderError("Unexpected EmailBison attach tags to campaigns response type")


def remove_tags_from_campaigns(
    api_key: str,
    tag_ids: list[int],
    campaign_ids: list[int],
    skip_webhooks: bool | None = None,
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"tag_ids": tag_ids, "campaign_ids": campaign_ids}
    if skip_webhooks is not None:
        payload["skip_webhooks"] = skip_webhooks
    data = _request_json(
        method="POST",
        candidate_paths=[f"{_EP_TAGS}/remove-from-campaigns"],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
        json_payload=payload,
    )
    if isinstance(data, dict):
        return data
    raise EmailBisonProviderError("Unexpected EmailBison remove tags from campaigns response type")


def attach_tags_to_sender_emails(
    api_key: str,
    tag_ids: list[int],
    sender_email_ids: list[int],
    skip_webhooks: bool | None = None,
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"tag_ids": tag_ids, "sender_email_ids": sender_email_ids}
    if skip_webhooks is not None:
        payload["skip_webhooks"] = skip_webhooks
    data = _request_json(
        method="POST",
        candidate_paths=[f"{_EP_TAGS}/attach-to-sender-emails"],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
        json_payload=payload,
    )
    if isinstance(data, dict):
        return data
    raise EmailBisonProviderError("Unexpected EmailBison attach tags to sender emails response type")


def remove_tags_from_sender_emails(
    api_key: str,
    tag_ids: list[int],
    sender_email_ids: list[int],
    skip_webhooks: bool | None = None,
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"tag_ids": tag_ids, "sender_email_ids": sender_email_ids}
    if skip_webhooks is not None:
        payload["skip_webhooks"] = skip_webhooks
    data = _request_json(
        method="POST",
        candidate_paths=[f"{_EP_TAGS}/remove-from-sender-emails"],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
        json_payload=payload,
    )
    if isinstance(data, dict):
        return data
    raise EmailBisonProviderError("Unexpected EmailBison remove tags from sender emails response type")


def list_custom_variables(
    api_key: str,
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> list[dict[str, Any]]:
    data = _request_json(
        method="GET",
        candidate_paths=[_EP_CUSTOM_VARIABLES],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
    )
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return data["items"]
    raise EmailBisonProviderError("Unexpected EmailBison custom variables response shape")


def create_custom_variable(
    api_key: str,
    name: str,
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    data = _request_json(
        method="POST",
        candidate_paths=[_EP_CUSTOM_VARIABLES],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
        json_payload={"name": name},
    )
    if isinstance(data, dict):
        return data
    raise EmailBisonProviderError("Unexpected EmailBison create custom variable response type")


def list_blacklisted_emails(
    api_key: str,
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> list[dict[str, Any]]:
    data = _request_json(
        method="GET",
        candidate_paths=[_EP_BLACKLISTED_EMAILS],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
    )
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return data["items"]
    raise EmailBisonProviderError("Unexpected EmailBison blacklisted emails response shape")


def create_blacklisted_email(
    api_key: str,
    email: str,
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    data = _request_json(
        method="POST",
        candidate_paths=[_EP_BLACKLISTED_EMAILS],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
        json_payload={"email": email},
    )
    if isinstance(data, dict):
        return data
    raise EmailBisonProviderError("Unexpected EmailBison create blacklisted email response type")


def bulk_create_blacklisted_emails(
    api_key: str,
    emails: list[str],
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> list[dict[str, Any]]:
    data = _request_json(
        method="POST",
        candidate_paths=[f"{_EP_BLACKLISTED_EMAILS}/bulk"],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
        json_payload={"emails": emails},
    )
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return data["items"]
    raise EmailBisonProviderError("Unexpected EmailBison bulk blacklisted emails response shape")


def delete_blacklisted_email(
    api_key: str,
    blacklisted_email_id: int | str,
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    data = _request_json(
        method="DELETE",
        candidate_paths=[f"{_EP_BLACKLISTED_EMAILS}/{blacklisted_email_id}"],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
    )
    if isinstance(data, dict):
        return data
    raise EmailBisonProviderError("Unexpected EmailBison delete blacklisted email response type")


def list_blacklisted_domains(
    api_key: str,
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> list[dict[str, Any]]:
    data = _request_json(
        method="GET",
        candidate_paths=[_EP_BLACKLISTED_DOMAINS],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
    )
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return data["items"]
    raise EmailBisonProviderError("Unexpected EmailBison blacklisted domains response shape")


def create_blacklisted_domain(
    api_key: str,
    domain: str,
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    data = _request_json(
        method="POST",
        candidate_paths=[_EP_BLACKLISTED_DOMAINS],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
        json_payload={"domain": domain},
    )
    if isinstance(data, dict):
        return data
    raise EmailBisonProviderError("Unexpected EmailBison create blacklisted domain response type")


def bulk_create_blacklisted_domains(
    api_key: str,
    domains: list[str],
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> list[dict[str, Any]]:
    data = _request_json(
        method="POST",
        candidate_paths=[f"{_EP_BLACKLISTED_DOMAINS}/bulk"],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
        json_payload={"domains": domains},
    )
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return data["items"]
    raise EmailBisonProviderError("Unexpected EmailBison bulk blacklisted domains response shape")


def delete_blacklisted_domain(
    api_key: str,
    blacklisted_domain_id: int | str,
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    data = _request_json(
        method="DELETE",
        candidate_paths=[f"{_EP_BLACKLISTED_DOMAINS}/{blacklisted_domain_id}"],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
    )
    if isinstance(data, dict):
        return data
    raise EmailBisonProviderError("Unexpected EmailBison delete blacklisted domain response type")


def get_workspace_account_details(
    api_key: str,
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    data = _request_json(
        method="GET",
        candidate_paths=[_EP_USERS],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
    )
    if isinstance(data, dict):
        return data
    raise EmailBisonProviderError("Unexpected EmailBison workspace account details response type")


def get_workspace_stats(
    api_key: str,
    start_date: str,
    end_date: str,
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    data = _request_json(
        method="GET",
        candidate_paths=[_EP_WORKSPACE_STATS],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
        params={"start_date": start_date, "end_date": end_date},
    )
    if isinstance(data, dict):
        return data
    raise EmailBisonProviderError("Unexpected EmailBison workspace stats response type")


def get_workspace_master_inbox_settings(
    api_key: str,
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    data = _request_json(
        method="GET",
        candidate_paths=[_EP_MASTER_INBOX_SETTINGS],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
    )
    if isinstance(data, dict):
        return data
    raise EmailBisonProviderError("Unexpected EmailBison master inbox settings response type")


def update_workspace_master_inbox_settings(
    api_key: str,
    updates: dict[str, Any],
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    data = _request_json(
        method="PATCH",
        candidate_paths=[_EP_MASTER_INBOX_SETTINGS],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
        json_payload=updates,
    )
    if isinstance(data, dict):
        return data
    raise EmailBisonProviderError("Unexpected EmailBison update master inbox settings response type")


def get_campaign_events_stats(
    api_key: str,
    start_date: str,
    end_date: str,
    sender_email_ids: list[int] | None = None,
    campaign_ids: list[int] | None = None,
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"start_date": start_date, "end_date": end_date}
    if sender_email_ids is not None:
        params["sender_email_ids"] = sender_email_ids
    if campaign_ids is not None:
        params["campaign_ids"] = campaign_ids
    data = _request_json(
        method="GET",
        candidate_paths=[_EP_CAMPAIGN_EVENTS_STATS],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
        params=params,
    )
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return data["items"]
    raise EmailBisonProviderError("Unexpected EmailBison campaign events stats response shape")


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


def get_reply(
    api_key: str,
    reply_id: int | str,
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    data = _request_json(
        method="GET",
        candidate_paths=[f"/api/replies/{reply_id}"],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
    )
    if isinstance(data, dict):
        return data
    raise EmailBisonProviderError("Unexpected EmailBison get reply response type")


def get_reply_conversation_thread(
    api_key: str,
    reply_id: int | str,
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    data = _request_json(
        method="GET",
        candidate_paths=[f"/api/replies/{reply_id}/conversation-thread"],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
    )
    if isinstance(data, dict):
        return data
    raise EmailBisonProviderError("Unexpected EmailBison reply thread response type")


def list_campaign_replies(
    api_key: str,
    campaign_id: int | str,
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> list[dict[str, Any]]:
    data = _request_json(
        method="GET",
        candidate_paths=[f"/api/campaigns/{campaign_id}/replies"],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
    )
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return data["items"]
    raise EmailBisonProviderError("Unexpected EmailBison campaign replies response shape")


def list_lead_replies(
    api_key: str,
    lead_id: int | str,
    instance_url: str | None = None,
    timeout_seconds: float = 12.0,
) -> list[dict[str, Any]]:
    data = _request_json(
        method="GET",
        candidate_paths=[f"/api/leads/{lead_id}/replies"],
        api_key=api_key,
        instance_url=instance_url,
        timeout_seconds=timeout_seconds,
    )
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return data["items"]
    raise EmailBisonProviderError("Unexpected EmailBison lead replies response shape")


EMAILBISON_IMPLEMENTED_ENDPOINT_REGISTRY: dict[str, list[dict[str, str]]] = {
    "validate_api_key": [{"method": "GET", "path": _EP_USERS}],
    "list_campaigns": [{"method": "GET", "path": _EP_CAMPAIGNS}],
    "create_campaign": [{"method": "POST", "path": _EP_CAMPAIGNS}],
    "update_campaign_status": [
        {"method": "PATCH", "path": "/api/campaigns/{campaign_id}/resume"},
        {"method": "PATCH", "path": "/api/campaigns/{campaign_id}/pause"},
        {"method": "PATCH", "path": "/api/campaigns/{campaign_id}/archive"},
    ],
    "get_campaign_sequence_steps": [{"method": "GET", "path": "/api/campaigns/{campaign_id}/sequence-steps"}],
    "create_campaign_sequence_steps": [{"method": "POST", "path": "/api/campaigns/{campaign_id}/sequence-steps"}],
    "get_campaign_schedule": [{"method": "GET", "path": "/api/campaigns/{campaign_id}/schedule"}],
    "create_campaign_schedule": [{"method": "POST", "path": "/api/campaigns/{campaign_id}/schedule"}],
    "get_campaign_sending_schedule": [{"method": "GET", "path": "/api/campaigns/{campaign_id}/sending-schedule"}],
    "get_campaign_sender_emails": [{"method": "GET", "path": "/api/campaigns/{campaign_id}/sender-emails"}],
    "get_campaign_line_area_chart_stats": [{"method": "GET", "path": "/api/campaigns/{campaign_id}/line-area-chart-stats"}],
    "list_leads": [{"method": "GET", "path": _EP_LEADS}],
    "create_lead": [{"method": "POST", "path": _EP_LEADS}],
    "create_leads_bulk": [{"method": "POST", "path": "/api/leads/multiple"}],
    "create_or_update_leads_bulk": [{"method": "POST", "path": "/api/leads/create-or-update/multiple"}],
    "get_lead": [{"method": "GET", "path": "/api/leads/{lead_id}"}],
    "update_lead": [{"method": "PATCH|PUT", "path": "/api/leads/{lead_id}"}],
    "update_lead_status": [{"method": "PATCH", "path": "/api/leads/{lead_id}/update-status"}],
    "unsubscribe_lead": [{"method": "PATCH", "path": "/api/leads/{lead_id}/unsubscribe"}],
    "delete_lead": [{"method": "DELETE", "path": "/api/leads/{lead_id}"}],
    "list_campaign_leads": [{"method": "GET", "path": "/api/campaigns/{campaign_id}/leads"}],
    "attach_leads_to_campaign": [{"method": "POST", "path": "/api/campaigns/{campaign_id}/leads/attach-leads"}],
    "attach_lead_list_to_campaign": [{"method": "POST", "path": "/api/campaigns/{campaign_id}/leads/attach-lead-list"}],
    "stop_future_emails_for_leads": [{"method": "POST", "path": "/api/campaigns/{campaign_id}/leads/stop-future-emails"}],
    "remove_leads_from_campaign": [{"method": "DELETE", "path": "/api/campaigns/{campaign_id}/leads"}],
    "list_replies": [{"method": "GET", "path": _EP_REPLIES}],
    "get_reply": [{"method": "GET", "path": "/api/replies/{id}"}],
    "get_reply_conversation_thread": [{"method": "GET", "path": "/api/replies/{reply_id}/conversation-thread"}],
    "list_campaign_replies": [{"method": "GET", "path": "/api/campaigns/{campaign_id}/replies"}],
    "list_lead_replies": [{"method": "GET", "path": "/api/leads/{lead_id}/replies"}],
    "get_campaign_stats": [{"method": "GET", "path": "/api/campaigns/{campaign_id}/stats"}],
    "list_sender_emails": [{"method": "GET", "path": _EP_SENDER_EMAILS}],
    "get_sender_email": [{"method": "GET", "path": "/api/sender-emails/{senderEmailId}"}],
    "update_sender_email": [{"method": "PATCH", "path": "/api/sender-emails/{senderEmailId}"}],
    "delete_sender_email": [{"method": "DELETE", "path": "/api/sender-emails/{senderEmailId}"}],
    "list_sender_emails_with_warmup_stats": [{"method": "GET", "path": "/api/warmup/sender-emails"}],
    "get_sender_email_warmup_details": [{"method": "GET", "path": "/api/warmup/sender-emails/{senderEmailId}"}],
    "enable_warmup_for_sender_emails": [{"method": "PATCH", "path": "/api/warmup/sender-emails/enable"}],
    "disable_warmup_for_sender_emails": [{"method": "PATCH", "path": "/api/warmup/sender-emails/disable"}],
    "update_sender_email_daily_warmup_limits": [
        {"method": "PATCH", "path": "/api/warmup/sender-emails/update-daily-warmup-limits"}
    ],
    "check_sender_email_mx_records": [{"method": "POST", "path": "/api/sender-emails/{senderEmailId}/check-mx-records"}],
    "bulk_check_missing_mx_records": [{"method": "POST", "path": "/api/sender-emails/bulk-check-missing-mx-records"}],
    "list_tags": [{"method": "GET", "path": _EP_TAGS}],
    "create_tag": [{"method": "POST", "path": _EP_TAGS}],
    "get_tag": [{"method": "GET", "path": "/api/tags/{id}"}],
    "delete_tag": [{"method": "DELETE", "path": "/api/tags/{tag_id}"}],
    "attach_tags_to_leads": [{"method": "POST", "path": "/api/tags/attach-to-leads"}],
    "remove_tags_from_leads": [{"method": "POST", "path": "/api/tags/remove-from-leads"}],
    "attach_tags_to_campaigns": [{"method": "POST", "path": "/api/tags/attach-to-campaigns"}],
    "remove_tags_from_campaigns": [{"method": "POST", "path": "/api/tags/remove-from-campaigns"}],
    "attach_tags_to_sender_emails": [{"method": "POST", "path": "/api/tags/attach-to-sender-emails"}],
    "remove_tags_from_sender_emails": [{"method": "POST", "path": "/api/tags/remove-from-sender-emails"}],
    "list_custom_variables": [{"method": "GET", "path": _EP_CUSTOM_VARIABLES}],
    "create_custom_variable": [{"method": "POST", "path": _EP_CUSTOM_VARIABLES}],
    "list_blacklisted_emails": [{"method": "GET", "path": _EP_BLACKLISTED_EMAILS}],
    "create_blacklisted_email": [{"method": "POST", "path": _EP_BLACKLISTED_EMAILS}],
    "bulk_create_blacklisted_emails": [{"method": "POST", "path": "/api/blacklisted-emails/bulk"}],
    "delete_blacklisted_email": [{"method": "DELETE", "path": "/api/blacklisted-emails/{blacklisted_email_id}"}],
    "list_blacklisted_domains": [{"method": "GET", "path": _EP_BLACKLISTED_DOMAINS}],
    "create_blacklisted_domain": [{"method": "POST", "path": _EP_BLACKLISTED_DOMAINS}],
    "bulk_create_blacklisted_domains": [{"method": "POST", "path": "/api/blacklisted-domains/bulk"}],
    "delete_blacklisted_domain": [{"method": "DELETE", "path": "/api/blacklisted-domains/{blacklisted_domain_id}"}],
    "get_workspace_account_details": [{"method": "GET", "path": _EP_USERS}],
    "get_workspace_stats": [{"method": "GET", "path": _EP_WORKSPACE_STATS}],
    "get_workspace_master_inbox_settings": [{"method": "GET", "path": _EP_MASTER_INBOX_SETTINGS}],
    "update_workspace_master_inbox_settings": [{"method": "PATCH", "path": _EP_MASTER_INBOX_SETTINGS}],
    "get_campaign_events_stats": [{"method": "GET", "path": _EP_CAMPAIGN_EVENTS_STATS}],
    "delete_webhook": [{"method": "DELETE", "path": "/api/webhook-url/{id}"}],
}


EMAILBISON_CONTRACT_STATUS_REGISTRY: dict[str, dict[str, str]] = {
    "custom_variables.update": {
        "status": "blocked_contract_missing",
        "evidence": "Live user-emailbison API spec output currently surfaces GET/POST /api/custom-variables only; no update endpoint found.",
    },
    "custom_variables.delete": {
        "status": "blocked_contract_missing",
        "evidence": "Live user-emailbison API spec output currently surfaces GET/POST /api/custom-variables only; no delete endpoint found.",
    },
    "tags.update": {
        "status": "blocked_contract_missing",
        "evidence": "Live user-emailbison API spec output currently surfaces GET/POST /api/tags, GET /api/tags/{id}, and DELETE /api/tags/{tag_id}; no update endpoint found.",
    },
}
