from __future__ import annotations

import random
import time
from typing import Any

import httpx


VOICEDROP_API_BASE = "https://api.voicedrop.ai"

_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
_MAX_RETRY_ATTEMPTS = 3
_RETRY_BASE_DELAY_SECONDS = 0.25
_RETRY_MAX_DELAY_SECONDS = 2.0

_EP_RINGLESS_VOICEMAIL = "/v1/ringless_voicemail"
_EP_VOICE_CLONES = "/v1/voice-clones"
_EP_VOICE_CLONE = "/v1/voice-clone"
_EP_SENDER_NUMBERS = "/v1/sender-numbers"
_EP_PROFILE = "/v1/profile"
_EP_DNC = "/v1/add-to-dnc-list"
_EP_CAMPAIGNS = "/v1/campaigns"
_EP_UPLOAD_AUDIO = "/v1/upload_static_audio"


class VoiceDropProviderError(Exception):
    """Provider-level exception for VoiceDrop integration failures."""

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
            "invalid voicedrop api key" in message
            or "endpoint not found" in message
            or "missing voicedrop api key" in message
            or "missing voice generation parameters" in message
            or "unexpected voicedrop" in message
        ):
            return "terminal"
        return "unknown"

    @property
    def retryable(self) -> bool:
        return self.category == "transient"


def _build_base_url(base_url: str | None) -> str:
    return (base_url or VOICEDROP_API_BASE).rstrip("/")


def _headers(api_key: str) -> dict[str, str]:
    return {
        "auth-key": api_key,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


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


def _request_json(
    *,
    method: str,
    path: str,
    api_key: str,
    base_url: str | None = None,
    timeout_seconds: float = 12.0,
    params: dict[str, Any] | None = None,
    json_payload: dict[str, Any] | None = None,
) -> Any:
    if not api_key:
        raise VoiceDropProviderError("Missing VoiceDrop API key")

    url = f"{_build_base_url(base_url)}{path}"
    try:
        response = _request_with_retry(
            method=method,
            url=url,
            headers=_headers(api_key),
            timeout_seconds=timeout_seconds,
            params=params,
            json_payload=json_payload,
        )
    except httpx.HTTPError as exc:
        raise VoiceDropProviderError(f"VoiceDrop connectivity error: {exc}") from exc

    if response.status_code in {401, 403}:
        raise VoiceDropProviderError("Invalid VoiceDrop API key")
    if response.status_code == 404:
        raise VoiceDropProviderError(f"VoiceDrop endpoint not found: {path}")
    if response.status_code >= 400:
        raise VoiceDropProviderError(f"VoiceDrop API returned HTTP {response.status_code}: {response.text[:200]}")

    try:
        return response.json()
    except ValueError as exc:
        raise VoiceDropProviderError("VoiceDrop returned non-JSON response") from exc


def send_ringless_voicemail(
    api_key: str,
    *,
    to: str,
    from_number: str,
    voice_clone_id: str | None = None,
    script: str | None = None,
    recording_url: str | None = None,
    validate_recipient_phone: bool = False,
    send_status_to_webhook: str | None = None,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    if recording_url:
        payload: dict[str, Any] = {
            "recording_url": recording_url,
            "to": to,
            "from": from_number,
            "validate_recipient_phone": validate_recipient_phone,
        }
    elif voice_clone_id and script:
        payload = {
            "voice_clone_id": voice_clone_id,
            "script": script,
            "to": to,
            "from": from_number,
            "validate_recipient_phone": validate_recipient_phone,
        }
    else:
        raise VoiceDropProviderError(
            "Missing voice generation parameters: provide recording_url or both voice_clone_id and script"
        )

    if send_status_to_webhook is not None:
        payload["send_status_to_webhook"] = send_status_to_webhook

    data = _request_json(
        method="POST",
        path=_EP_RINGLESS_VOICEMAIL,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
        json_payload=payload,
    )
    if isinstance(data, dict):
        return data
    raise VoiceDropProviderError("Unexpected VoiceDrop ringless voicemail response type")


def create_voice_clone(
    api_key: str,
    *,
    display_name: str,
    recording_url: str,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    data = _request_json(
        method="POST",
        path=_EP_VOICE_CLONE,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
        json_payload={"display_name": display_name, "recording_url": recording_url},
    )
    if isinstance(data, dict):
        return data
    raise VoiceDropProviderError("Unexpected VoiceDrop create voice clone response type")


def list_voice_clones(
    api_key: str,
    *,
    timeout_seconds: float = 12.0,
) -> list[dict[str, Any]]:
    data = _request_json(
        method="GET",
        path=_EP_VOICE_CLONES,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
    )
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("voice_clones"), list):
        return data["voice_clones"]
    raise VoiceDropProviderError("Unexpected VoiceDrop list voice clones response shape")


def delete_voice_clone(
    api_key: str,
    *,
    voice_clone_id: str,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    data = _request_json(
        method="DELETE",
        path=f"{_EP_VOICE_CLONE}/{voice_clone_id}",
        api_key=api_key,
        timeout_seconds=timeout_seconds,
    )
    if isinstance(data, dict):
        return data
    raise VoiceDropProviderError("Unexpected VoiceDrop delete voice clone response type")


def preview_voice_clone(
    api_key: str,
    *,
    voice_clone_id: str,
    script: str,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    data = _request_json(
        method="POST",
        path=f"{_EP_VOICE_CLONE}/preview",
        api_key=api_key,
        timeout_seconds=timeout_seconds,
        json_payload={"voice_clone_id": voice_clone_id, "script": script},
    )
    if isinstance(data, dict):
        return data
    raise VoiceDropProviderError("Unexpected VoiceDrop preview voice clone response type")


def list_sender_numbers(
    api_key: str,
    *,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    data = _request_json(
        method="GET",
        path=_EP_SENDER_NUMBERS,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
    )
    if isinstance(data, dict):
        return data
    raise VoiceDropProviderError("Unexpected VoiceDrop sender numbers response type")


def validate_api_key(
    api_key: str,
    *,
    timeout_seconds: float = 8.0,
) -> None:
    _request_json(
        method="GET",
        path=_EP_PROFILE,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
    )


def add_to_dnc_list(
    api_key: str,
    *,
    phone: str,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    data = _request_json(
        method="POST",
        path=_EP_DNC,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
        json_payload={"phone": phone},
    )
    if isinstance(data, dict):
        return data
    raise VoiceDropProviderError("Unexpected VoiceDrop DNC response type")


def add_prospect_to_campaign(
    api_key: str,
    *,
    campaign_id: str,
    prospect_phone: str,
    personalization_variables: dict[str, Any] | None = None,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"prospect_phone": prospect_phone}
    if personalization_variables is not None:
        payload["personalization_variables"] = personalization_variables
    data = _request_json(
        method="POST",
        path=f"{_EP_CAMPAIGNS}/{campaign_id}/prospects",
        api_key=api_key,
        timeout_seconds=timeout_seconds,
        json_payload=payload,
    )
    if isinstance(data, dict):
        return data
    raise VoiceDropProviderError("Unexpected VoiceDrop add prospect response type")


def list_campaigns(
    api_key: str,
    *,
    timeout_seconds: float = 12.0,
) -> list[dict[str, Any]]:
    data = _request_json(
        method="GET",
        path=_EP_CAMPAIGNS,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
    )
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("campaigns"), list):
        return data["campaigns"]
    raise VoiceDropProviderError("Unexpected VoiceDrop list campaigns response shape")


def verify_sender_number_start(
    api_key: str,
    *,
    phone_number: str,
    method: str = "sms",
    timeout_seconds: float = 12.0,
) -> dict[str, Any] | None:
    data = _request_json(
        method="POST",
        path=f"{_EP_SENDER_NUMBERS}/verify",
        api_key=api_key,
        timeout_seconds=timeout_seconds,
        json_payload={"phone_number": phone_number, "method": method},
    )
    if isinstance(data, dict):
        return data
    return None


def verify_sender_number_complete(
    api_key: str,
    *,
    phone_number: str,
    code: str,
    timeout_seconds: float = 12.0,
) -> dict[str, Any] | None:
    data = _request_json(
        method="POST",
        path=f"{_EP_SENDER_NUMBERS}/verify",
        api_key=api_key,
        timeout_seconds=timeout_seconds,
        json_payload={"phone_number": phone_number, "code": code},
    )
    if isinstance(data, dict):
        return data
    return None


def export_campaign_reports(
    api_key: str,
    *,
    campaign_id: str,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    data = _request_json(
        method="GET",
        path=f"{_EP_CAMPAIGNS}/{campaign_id}/reports",
        api_key=api_key,
        timeout_seconds=timeout_seconds,
    )
    if isinstance(data, dict):
        return data
    raise VoiceDropProviderError("Unexpected VoiceDrop campaign reports response type")


def set_campaign_status(
    api_key: str,
    *,
    campaign_id: str,
    status: str,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    data = _request_json(
        method="PATCH",
        path=f"{_EP_CAMPAIGNS}/{campaign_id}",
        api_key=api_key,
        timeout_seconds=timeout_seconds,
        json_payload={"status": status},
    )
    if isinstance(data, dict):
        return data
    raise VoiceDropProviderError("Unexpected VoiceDrop campaign status response type")
