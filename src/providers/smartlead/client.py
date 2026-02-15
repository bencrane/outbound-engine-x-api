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
