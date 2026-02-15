from __future__ import annotations

from typing import Any

import httpx


SMARTLEAD_API_BASE = "https://server.smartlead.ai/api/v1"


class SmartleadProviderError(Exception):
    """Provider-level exception for Smartlead integration failures."""


def validate_api_key(api_key: str, timeout_seconds: float = 8.0) -> None:
    """
    Validate Smartlead API key by making a lightweight API call.

    Raises SmartleadProviderError on failure.
    """
    if not api_key:
        raise SmartleadProviderError("Missing Smartlead API key")

    url = f"{SMARTLEAD_API_BASE}/campaigns"
    params: dict[str, Any] = {"api_key": api_key, "limit": 1}

    try:
        with httpx.Client(timeout=timeout_seconds) as client:
            response = client.get(url, params=params)
    except httpx.HTTPError as exc:
        raise SmartleadProviderError(f"Smartlead connectivity error: {exc}") from exc

    if response.status_code == 401:
        raise SmartleadProviderError("Invalid Smartlead API key")
    if response.status_code >= 400:
        raise SmartleadProviderError(
            f"Smartlead API returned HTTP {response.status_code}: {response.text[:200]}"
        )


def list_email_accounts(api_key: str, timeout_seconds: float = 12.0) -> list[dict[str, Any]]:
    """
    Fetch Smartlead email accounts and normalize to dict payloads.

    Returns raw account objects as provided by Smartlead.
    Raises SmartleadProviderError on failure.
    """
    if not api_key:
        raise SmartleadProviderError("Missing Smartlead API key")

    # Smartlead has used both forms in different docs/deployments.
    candidate_urls = [
        f"{SMARTLEAD_API_BASE}/email-accounts",
        f"{SMARTLEAD_API_BASE}/email-accounts/",
    ]

    last_error: str | None = None
    for url in candidate_urls:
        try:
            with httpx.Client(timeout=timeout_seconds) as client:
                response = client.get(url, params={"api_key": api_key})
        except httpx.HTTPError as exc:
            last_error = f"Smartlead connectivity error: {exc}"
            continue

        if response.status_code == 404:
            last_error = "Smartlead email-accounts endpoint not found"
            continue
        if response.status_code == 401:
            raise SmartleadProviderError("Invalid Smartlead API key")
        if response.status_code >= 400:
            raise SmartleadProviderError(
                f"Smartlead API returned HTTP {response.status_code}: {response.text[:200]}"
            )

        payload = response.json()
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            if isinstance(payload.get("data"), list):
                return payload["data"]
            if isinstance(payload.get("items"), list):
                return payload["items"]
            # Unexpected but valid JSON shape.
            raise SmartleadProviderError("Unexpected Smartlead email-accounts response shape")

        raise SmartleadProviderError("Unexpected Smartlead email-accounts response type")

    raise SmartleadProviderError(last_error or "Unable to fetch Smartlead email accounts")


def list_campaigns(
    api_key: str,
    limit: int = 100,
    offset: int = 0,
    timeout_seconds: float = 12.0,
) -> list[dict[str, Any]]:
    """Fetch Smartlead campaigns."""
    if not api_key:
        raise SmartleadProviderError("Missing Smartlead API key")

    candidate_urls = [
        f"{SMARTLEAD_API_BASE}/campaigns",
        f"{SMARTLEAD_API_BASE}/campaign/list",
    ]
    params = {"api_key": api_key, "limit": limit, "offset": offset}
    last_error: str | None = None
    for url in candidate_urls:
        try:
            with httpx.Client(timeout=timeout_seconds) as client:
                response = client.get(url, params=params)
        except httpx.HTTPError as exc:
            last_error = f"Smartlead connectivity error: {exc}"
            continue

        if response.status_code == 404:
            last_error = "Smartlead campaigns endpoint not found"
            continue
        if response.status_code == 401:
            raise SmartleadProviderError("Invalid Smartlead API key")
        if response.status_code == 400 and "limit" in (response.text or "").lower():
            # Some Smartlead deployments reject limit/offset query args.
            try:
                with httpx.Client(timeout=timeout_seconds) as client:
                    response = client.get(url, params={"api_key": api_key})
            except httpx.HTTPError as exc:
                last_error = f"Smartlead connectivity error: {exc}"
                continue
        if response.status_code >= 400:
            raise SmartleadProviderError(
                f"Smartlead API returned HTTP {response.status_code}: {response.text[:200]}"
            )

        payload = response.json()
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            if isinstance(payload.get("data"), list):
                return payload["data"]
            if isinstance(payload.get("items"), list):
                return payload["items"]
            raise SmartleadProviderError("Unexpected Smartlead campaigns response shape")
        raise SmartleadProviderError("Unexpected Smartlead campaigns response type")

    raise SmartleadProviderError(last_error or "Unable to fetch Smartlead campaigns")


def create_campaign(api_key: str, name: str, client_id: int, timeout_seconds: float = 12.0) -> dict[str, Any]:
    """
    Create a Smartlead campaign for a specific client.

    Raises SmartleadProviderError on failure.
    """
    if not api_key:
        raise SmartleadProviderError("Missing Smartlead API key")
    if not name:
        raise SmartleadProviderError("Campaign name is required")

    candidate_urls = [
        f"{SMARTLEAD_API_BASE}/campaigns/create",
        f"{SMARTLEAD_API_BASE}/campaigns",
    ]
    payload = {"name": name, "client_id": client_id}

    last_error: str | None = None
    for url in candidate_urls:
        try:
            with httpx.Client(timeout=timeout_seconds) as client:
                response = client.post(url, params={"api_key": api_key}, json=payload)
        except httpx.HTTPError as exc:
            last_error = f"Smartlead connectivity error: {exc}"
            continue

        if response.status_code == 404:
            last_error = "Smartlead campaign create endpoint not found"
            continue
        if response.status_code == 401:
            raise SmartleadProviderError("Invalid Smartlead API key")
        if response.status_code >= 400:
            raise SmartleadProviderError(
                f"Smartlead API returned HTTP {response.status_code}: {response.text[:200]}"
            )

        data = response.json()
        if isinstance(data, dict):
            return data
        raise SmartleadProviderError("Unexpected Smartlead create-campaign response type")

    raise SmartleadProviderError(last_error or "Unable to create Smartlead campaign")


def update_campaign_status(
    api_key: str,
    campaign_id: int | str,
    status_value: str,
    timeout_seconds: float = 10.0,
) -> dict[str, Any]:
    """
    Update Smartlead campaign status.

    Raises SmartleadProviderError on failure.
    """
    if not api_key:
        raise SmartleadProviderError("Missing Smartlead API key")

    candidate_urls = [
        f"{SMARTLEAD_API_BASE}/campaigns/{campaign_id}/status",
        f"{SMARTLEAD_API_BASE}/campaigns/{campaign_id}/update-status",
    ]
    payload = {"status": status_value}

    last_error: str | None = None
    for url in candidate_urls:
        try:
            with httpx.Client(timeout=timeout_seconds) as client:
                response = client.post(url, params={"api_key": api_key}, json=payload)
        except httpx.HTTPError as exc:
            last_error = f"Smartlead connectivity error: {exc}"
            continue

        if response.status_code == 404:
            last_error = "Smartlead campaign status endpoint not found"
            continue
        if response.status_code == 401:
            raise SmartleadProviderError("Invalid Smartlead API key")
        if response.status_code >= 400:
            raise SmartleadProviderError(
                f"Smartlead API returned HTTP {response.status_code}: {response.text[:200]}"
            )

        data = response.json()
        if isinstance(data, dict):
            return data
        raise SmartleadProviderError("Unexpected Smartlead update-status response type")

    raise SmartleadProviderError(last_error or "Unable to update Smartlead campaign status")


def get_campaign_sequence(
    api_key: str,
    campaign_id: int | str,
    timeout_seconds: float = 10.0,
) -> list[dict[str, Any]]:
    """
    Fetch Smartlead campaign sequence.
    """
    if not api_key:
        raise SmartleadProviderError("Missing Smartlead API key")

    candidate_urls = [
        f"{SMARTLEAD_API_BASE}/campaigns/{campaign_id}/sequences",
        f"{SMARTLEAD_API_BASE}/campaigns/{campaign_id}/sequence",
    ]

    last_error: str | None = None
    for url in candidate_urls:
        try:
            with httpx.Client(timeout=timeout_seconds) as client:
                response = client.get(url, params={"api_key": api_key})
        except httpx.HTTPError as exc:
            last_error = f"Smartlead connectivity error: {exc}"
            continue

        if response.status_code == 404:
            last_error = "Smartlead sequence endpoint not found"
            continue
        if response.status_code == 401:
            raise SmartleadProviderError("Invalid Smartlead API key")
        if response.status_code >= 400:
            raise SmartleadProviderError(
                f"Smartlead API returned HTTP {response.status_code}: {response.text[:200]}"
            )

        payload = response.json()
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            if isinstance(payload.get("data"), list):
                return payload["data"]
            if isinstance(payload.get("sequences"), list):
                return payload["sequences"]
            raise SmartleadProviderError("Unexpected Smartlead sequence response shape")
        raise SmartleadProviderError("Unexpected Smartlead sequence response type")

    raise SmartleadProviderError(last_error or "Unable to fetch Smartlead campaign sequence")


def save_campaign_sequence(
    api_key: str,
    campaign_id: int | str,
    sequence: list[dict[str, Any]],
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    """
    Save Smartlead campaign sequence payload.
    """
    if not api_key:
        raise SmartleadProviderError("Missing Smartlead API key")

    candidate_urls = [
        f"{SMARTLEAD_API_BASE}/campaigns/{campaign_id}/sequences",
        f"{SMARTLEAD_API_BASE}/campaigns/{campaign_id}/sequence",
    ]
    payload = {"sequence": sequence}

    last_error: str | None = None
    for url in candidate_urls:
        try:
            with httpx.Client(timeout=timeout_seconds) as client:
                response = client.post(url, params={"api_key": api_key}, json=payload)
        except httpx.HTTPError as exc:
            last_error = f"Smartlead connectivity error: {exc}"
            continue

        if response.status_code == 404:
            last_error = "Smartlead sequence save endpoint not found"
            continue
        if response.status_code == 401:
            raise SmartleadProviderError("Invalid Smartlead API key")
        if response.status_code >= 400:
            raise SmartleadProviderError(
                f"Smartlead API returned HTTP {response.status_code}: {response.text[:200]}"
            )

        data = response.json()
        if isinstance(data, dict):
            return data
        raise SmartleadProviderError("Unexpected Smartlead save-sequence response type")

    raise SmartleadProviderError(last_error or "Unable to save Smartlead campaign sequence")


def add_campaign_leads(
    api_key: str,
    campaign_id: int | str,
    leads: list[dict[str, Any]],
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    """Add leads to a Smartlead campaign."""
    if not api_key:
        raise SmartleadProviderError("Missing Smartlead API key")

    candidate_urls = [
        f"{SMARTLEAD_API_BASE}/campaigns/{campaign_id}/leads",
        f"{SMARTLEAD_API_BASE}/campaigns/{campaign_id}/add-leads",
    ]
    payload = {"leads": leads}
    last_error: str | None = None

    for url in candidate_urls:
        try:
            with httpx.Client(timeout=timeout_seconds) as client:
                response = client.post(url, params={"api_key": api_key}, json=payload)
        except httpx.HTTPError as exc:
            last_error = f"Smartlead connectivity error: {exc}"
            continue

        if response.status_code == 404:
            last_error = "Smartlead add-leads endpoint not found"
            continue
        if response.status_code == 401:
            raise SmartleadProviderError("Invalid Smartlead API key")
        if response.status_code >= 400:
            raise SmartleadProviderError(
                f"Smartlead API returned HTTP {response.status_code}: {response.text[:200]}"
            )

        data = response.json()
        if isinstance(data, dict):
            return data
        raise SmartleadProviderError("Unexpected Smartlead add-leads response type")

    raise SmartleadProviderError(last_error or "Unable to add leads to Smartlead campaign")


def get_campaign_leads(
    api_key: str,
    campaign_id: int | str,
    limit: int = 100,
    offset: int = 0,
    timeout_seconds: float = 12.0,
) -> list[dict[str, Any]]:
    """Fetch Smartlead leads for a campaign."""
    if not api_key:
        raise SmartleadProviderError("Missing Smartlead API key")

    candidate_urls = [
        f"{SMARTLEAD_API_BASE}/campaigns/{campaign_id}/leads",
        f"{SMARTLEAD_API_BASE}/campaigns/{campaign_id}/lead-list",
    ]
    params = {"api_key": api_key, "limit": limit, "offset": offset}
    last_error: str | None = None

    for url in candidate_urls:
        try:
            with httpx.Client(timeout=timeout_seconds) as client:
                response = client.get(url, params=params)
        except httpx.HTTPError as exc:
            last_error = f"Smartlead connectivity error: {exc}"
            continue

        if response.status_code == 404:
            last_error = "Smartlead campaign leads endpoint not found"
            continue
        if response.status_code == 401:
            raise SmartleadProviderError("Invalid Smartlead API key")
        if response.status_code >= 400:
            raise SmartleadProviderError(
                f"Smartlead API returned HTTP {response.status_code}: {response.text[:200]}"
            )

        payload = response.json()
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            if isinstance(payload.get("data"), list):
                return payload["data"]
            if isinstance(payload.get("items"), list):
                return payload["items"]
            raise SmartleadProviderError("Unexpected Smartlead campaign leads response shape")
        raise SmartleadProviderError("Unexpected Smartlead campaign leads response type")

    raise SmartleadProviderError(last_error or "Unable to fetch Smartlead campaign leads")


def _mutate_campaign_lead_status(
    api_key: str,
    campaign_id: int | str,
    lead_id: int | str,
    action: str,
    timeout_seconds: float = 10.0,
) -> dict[str, Any]:
    if not api_key:
        raise SmartleadProviderError("Missing Smartlead API key")

    candidate_urls = [
        f"{SMARTLEAD_API_BASE}/campaigns/{campaign_id}/leads/{lead_id}/{action}",
        f"{SMARTLEAD_API_BASE}/campaigns/{campaign_id}/lead/{lead_id}/{action}",
    ]
    last_error: str | None = None

    for url in candidate_urls:
        try:
            with httpx.Client(timeout=timeout_seconds) as client:
                response = client.post(url, params={"api_key": api_key})
        except httpx.HTTPError as exc:
            last_error = f"Smartlead connectivity error: {exc}"
            continue

        if response.status_code == 404:
            last_error = f"Smartlead lead {action} endpoint not found"
            continue
        if response.status_code == 401:
            raise SmartleadProviderError("Invalid Smartlead API key")
        if response.status_code >= 400:
            raise SmartleadProviderError(
                f"Smartlead API returned HTTP {response.status_code}: {response.text[:200]}"
            )

        data = response.json()
        if isinstance(data, dict):
            return data
        raise SmartleadProviderError(f"Unexpected Smartlead lead {action} response type")

    raise SmartleadProviderError(last_error or f"Unable to {action} Smartlead campaign lead")


def pause_campaign_lead(api_key: str, campaign_id: int | str, lead_id: int | str) -> dict[str, Any]:
    return _mutate_campaign_lead_status(api_key, campaign_id, lead_id, "pause")


def resume_campaign_lead(api_key: str, campaign_id: int | str, lead_id: int | str) -> dict[str, Any]:
    return _mutate_campaign_lead_status(api_key, campaign_id, lead_id, "resume")


def unsubscribe_campaign_lead(api_key: str, campaign_id: int | str, lead_id: int | str) -> dict[str, Any]:
    return _mutate_campaign_lead_status(api_key, campaign_id, lead_id, "unsubscribe")


def get_campaign_lead_messages(
    api_key: str,
    campaign_id: int | str,
    lead_id: int | str,
    timeout_seconds: float = 12.0,
) -> list[dict[str, Any]]:
    """Fetch message history for a campaign lead."""
    if not api_key:
        raise SmartleadProviderError("Missing Smartlead API key")

    candidate_urls = [
        f"{SMARTLEAD_API_BASE}/campaigns/{campaign_id}/leads/{lead_id}/messages",
        f"{SMARTLEAD_API_BASE}/campaigns/{campaign_id}/lead/{lead_id}/message-history",
    ]
    last_error: str | None = None
    for url in candidate_urls:
        try:
            with httpx.Client(timeout=timeout_seconds) as client:
                response = client.get(url, params={"api_key": api_key})
        except httpx.HTTPError as exc:
            last_error = f"Smartlead connectivity error: {exc}"
            continue

        if response.status_code == 404:
            last_error = "Smartlead lead message-history endpoint not found"
            continue
        if response.status_code == 401:
            raise SmartleadProviderError("Invalid Smartlead API key")
        if response.status_code >= 400:
            raise SmartleadProviderError(
                f"Smartlead API returned HTTP {response.status_code}: {response.text[:200]}"
            )

        payload = response.json()
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            if isinstance(payload.get("data"), list):
                return payload["data"]
            if isinstance(payload.get("messages"), list):
                return payload["messages"]
            raise SmartleadProviderError("Unexpected Smartlead lead messages response shape")
        raise SmartleadProviderError("Unexpected Smartlead lead messages response type")

    raise SmartleadProviderError(last_error or "Unable to fetch Smartlead lead messages")


def get_campaign_replies(
    api_key: str,
    campaign_id: int | str,
    timeout_seconds: float = 12.0,
) -> list[dict[str, Any]]:
    """Fetch inbound replies for a campaign."""
    if not api_key:
        raise SmartleadProviderError("Missing Smartlead API key")

    candidate_urls = [
        f"{SMARTLEAD_API_BASE}/campaigns/{campaign_id}/replies",
        f"{SMARTLEAD_API_BASE}/campaigns/{campaign_id}/reply-history",
    ]
    last_error: str | None = None
    for url in candidate_urls:
        try:
            with httpx.Client(timeout=timeout_seconds) as client:
                response = client.get(url, params={"api_key": api_key})
        except httpx.HTTPError as exc:
            last_error = f"Smartlead connectivity error: {exc}"
            continue

        if response.status_code == 404:
            last_error = "Smartlead campaign replies endpoint not found"
            continue
        if response.status_code == 401:
            raise SmartleadProviderError("Invalid Smartlead API key")
        if response.status_code >= 400:
            raise SmartleadProviderError(
                f"Smartlead API returned HTTP {response.status_code}: {response.text[:200]}"
            )

        payload = response.json()
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            if isinstance(payload.get("data"), list):
                return payload["data"]
            if isinstance(payload.get("replies"), list):
                return payload["replies"]
            raise SmartleadProviderError("Unexpected Smartlead replies response shape")
        raise SmartleadProviderError("Unexpected Smartlead replies response type")

    raise SmartleadProviderError(last_error or "Unable to fetch Smartlead campaign replies")


def get_campaign_analytics(
    api_key: str,
    campaign_id: int | str,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    """Fetch campaign analytics/statistics from Smartlead."""
    if not api_key:
        raise SmartleadProviderError("Missing Smartlead API key")

    candidate_urls = [
        f"{SMARTLEAD_API_BASE}/campaigns/{campaign_id}/stats",
        f"{SMARTLEAD_API_BASE}/campaigns/{campaign_id}/statistics",
        f"{SMARTLEAD_API_BASE}/campaigns/{campaign_id}/analytics",
    ]
    last_error: str | None = None

    for url in candidate_urls:
        try:
            with httpx.Client(timeout=timeout_seconds) as client:
                response = client.get(url, params={"api_key": api_key})
        except httpx.HTTPError as exc:
            last_error = f"Smartlead connectivity error: {exc}"
            continue

        if response.status_code == 404:
            last_error = "Smartlead campaign analytics endpoint not found"
            continue
        if response.status_code == 401:
            raise SmartleadProviderError("Invalid Smartlead API key")
        if response.status_code >= 400:
            raise SmartleadProviderError(
                f"Smartlead API returned HTTP {response.status_code}: {response.text[:200]}"
            )

        payload = response.json()
        if isinstance(payload, dict):
            return payload
        raise SmartleadProviderError("Unexpected Smartlead campaign analytics response type")

    raise SmartleadProviderError(last_error or "Unable to fetch Smartlead campaign analytics")
