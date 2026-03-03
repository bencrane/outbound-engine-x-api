from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from src.auth import AuthContext, get_current_auth
from src.db import supabase
from src.domain.provider_errors import provider_error_detail, provider_error_http_status
from src.providers.voicedrop.client import (
    VoiceDropProviderError,
    _request_json as voicedrop_request_json,
    add_to_dnc_list as voicedrop_add_to_dnc_list,
    create_voice_clone as voicedrop_create_voice_clone,
    delete_voice_clone as voicedrop_delete_voice_clone,
    list_sender_numbers as voicedrop_list_sender_numbers,
    list_voice_clones as voicedrop_list_voice_clones,
    preview_voice_clone as voicedrop_preview_voice_clone,
    send_ringless_voicemail as voicedrop_send_ringless_voicemail,
)


router = APIRouter(prefix="/api/voicemail", tags=["voicemail"])


class SendVoicemailRequest(BaseModel):
    company_id: str | None = None
    to: str
    from_number: str
    voice_clone_id: str | None = None
    script: str | None = None
    recording_url: str | None = None
    validate_recipient_phone: bool = False


class VoiceCloneCreateRequest(BaseModel):
    display_name: str
    recording_url: str


class VoiceClonePreviewRequest(BaseModel):
    script: str


class VerifySenderNumberRequest(BaseModel):
    phone_number: str
    method: Literal["sms", "call"] = "sms"


class VerifySenderNumberCodeRequest(BaseModel):
    phone_number: str
    code: str


class AddToDncRequest(BaseModel):
    phone: str


def _raise_provider_http_error(operation: str, exc: VoiceDropProviderError) -> None:
    raise HTTPException(
        status_code=provider_error_http_status(exc),
        detail=provider_error_detail(provider="voicedrop", operation=operation, exc=exc),
    ) from exc


def _resolve_company_id(auth: AuthContext, company_id: str | None) -> str:
    if auth.company_id:
        if company_id and company_id != auth.company_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")
        return auth.company_id
    if auth.role != "org_admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    if not company_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="company_id is required for org-level callers",
        )
    return company_id


def _get_company(org_id: str, company_id: str) -> dict[str, Any]:
    result = supabase.table("companies").select("id, org_id").eq("id", company_id).eq(
        "org_id", org_id
    ).is_("deleted_at", "null").execute()
    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")
    return result.data[0]


def _get_provider_by_id(provider_id: str) -> dict[str, Any]:
    provider = supabase.table("providers").select("id, slug").eq("id", provider_id).execute()
    if not provider.data:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Provider not configured")
    return provider.data[0]


def _ensure_voicedrop_provider(provider_slug: str) -> None:
    if provider_slug != "voicedrop":
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail={
                "type": "provider_not_implemented",
                "capability": "voicemail_drop",
                "provider": provider_slug,
                "message": f"voicemail_drop workflows are not implemented for provider: {provider_slug}",
            },
        )


def _get_voicemail_drop_provider(org_id: str, company_id: str) -> dict[str, Any]:
    capability = supabase.table("capabilities").select("id").eq("slug", "voicemail_drop").execute()
    if not capability.data:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Capability not configured")

    capability_id = capability.data[0]["id"]
    entitlement = supabase.table("company_entitlements").select("*").eq("org_id", org_id).eq(
        "company_id", company_id
    ).eq("capability_id", capability_id).is_("deleted_at", "null").execute()
    if not entitlement.data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Voicemail drop entitlement not found for company",
        )
    return entitlement.data[0]


def _get_org_voicedrop_config(org_id: str) -> dict[str, Any]:
    result = supabase.table("organizations").select("provider_configs").eq(
        "id", org_id
    ).is_("deleted_at", "null").execute()
    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    provider_configs = result.data[0].get("provider_configs") or {}
    provider_config = provider_configs.get("voicedrop") or {}
    api_key = provider_config.get("api_key")
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing org-level voicedrop API key",
        )
    return {"api_key": api_key}


def _resolve_voicemail_provider_creds(auth: AuthContext, company_id: str | None) -> tuple[str, dict[str, Any], dict[str, Any]]:
    resolved_company_id = _resolve_company_id(auth, company_id)
    _get_company(auth.org_id, resolved_company_id)
    entitlement = _get_voicemail_drop_provider(auth.org_id, resolved_company_id)
    provider = _get_provider_by_id(entitlement["provider_id"])
    _ensure_voicedrop_provider(provider["slug"])
    creds = _get_org_voicedrop_config(auth.org_id)
    return resolved_company_id, entitlement, creds


@router.post("/send")
async def send_voicemail(data: SendVoicemailRequest, auth: AuthContext = Depends(get_current_auth)):
    _, _, creds = _resolve_voicemail_provider_creds(auth, data.company_id)
    has_ai_voice = bool(data.voice_clone_id and data.script)
    has_static_audio = bool(data.recording_url)
    if has_ai_voice == has_static_audio:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide either recording_url or both voice_clone_id and script",
        )

    try:
        result = voicedrop_send_ringless_voicemail(
            creds["api_key"],
            to=data.to,
            from_number=data.from_number,
            voice_clone_id=data.voice_clone_id,
            script=data.script,
            recording_url=data.recording_url,
            validate_recipient_phone=data.validate_recipient_phone,
        )
    except VoiceDropProviderError as exc:
        _raise_provider_http_error("send_voicemail", exc)
    return {"provider": "voicemail_drop", "result": result}


@router.get("/voice-clones")
async def list_voice_clones(
    company_id: str | None = Query(None),
    auth: AuthContext = Depends(get_current_auth),
):
    _, _, creds = _resolve_voicemail_provider_creds(auth, company_id)
    try:
        rows = voicedrop_list_voice_clones(creds["api_key"])
    except VoiceDropProviderError as exc:
        _raise_provider_http_error("voice_clones_list", exc)
    return {"provider": "voicemail_drop", "voice_clones": rows}


@router.post("/voice-clones")
async def create_voice_clone(
    data: VoiceCloneCreateRequest,
    company_id: str | None = Query(None),
    auth: AuthContext = Depends(get_current_auth),
):
    _, _, creds = _resolve_voicemail_provider_creds(auth, company_id)
    try:
        row = voicedrop_create_voice_clone(
            creds["api_key"],
            display_name=data.display_name,
            recording_url=data.recording_url,
        )
    except VoiceDropProviderError as exc:
        _raise_provider_http_error("voice_clones_create", exc)
    return {"provider": "voicemail_drop", "voice_clone": row}


@router.delete("/voice-clones/{voice_clone_id}")
async def delete_voice_clone(
    voice_clone_id: str,
    company_id: str | None = Query(None),
    auth: AuthContext = Depends(get_current_auth),
):
    _, _, creds = _resolve_voicemail_provider_creds(auth, company_id)
    try:
        result = voicedrop_delete_voice_clone(creds["api_key"], voice_clone_id=voice_clone_id)
    except VoiceDropProviderError as exc:
        _raise_provider_http_error("voice_clones_delete", exc)
    return {"provider": "voicemail_drop", "result": result}


@router.post("/voice-clones/{voice_clone_id}/preview")
async def preview_voice_clone(
    voice_clone_id: str,
    data: VoiceClonePreviewRequest,
    company_id: str | None = Query(None),
    auth: AuthContext = Depends(get_current_auth),
):
    _, _, creds = _resolve_voicemail_provider_creds(auth, company_id)
    try:
        result = voicedrop_preview_voice_clone(
            creds["api_key"],
            voice_clone_id=voice_clone_id,
            script=data.script,
        )
    except VoiceDropProviderError as exc:
        _raise_provider_http_error("voice_clones_preview", exc)
    return {"provider": "voicemail_drop", "result": result}


@router.get("/sender-numbers")
async def list_sender_numbers(
    company_id: str | None = Query(None),
    auth: AuthContext = Depends(get_current_auth),
):
    _, _, creds = _resolve_voicemail_provider_creds(auth, company_id)
    try:
        rows = voicedrop_list_sender_numbers(creds["api_key"])
    except VoiceDropProviderError as exc:
        _raise_provider_http_error("sender_numbers_list", exc)
    return {"provider": "voicemail_drop", "sender_numbers": rows}


@router.post("/sender-numbers/verify")
async def verify_sender_number_start(
    data: VerifySenderNumberRequest,
    company_id: str | None = Query(None),
    auth: AuthContext = Depends(get_current_auth),
):
    _, _, creds = _resolve_voicemail_provider_creds(auth, company_id)
    try:
        result = voicedrop_request_json(
            method="POST",
            path="/v1/sender-numbers/verify",
            api_key=creds["api_key"],
            json_payload={"phone_number": data.phone_number, "method": data.method},
        )
    except VoiceDropProviderError as exc:
        _raise_provider_http_error("sender_numbers_verify_start", exc)
    return {"provider": "voicemail_drop", "result": result}


@router.post("/sender-numbers/verify-code")
async def verify_sender_number_complete(
    data: VerifySenderNumberCodeRequest,
    company_id: str | None = Query(None),
    auth: AuthContext = Depends(get_current_auth),
):
    _, _, creds = _resolve_voicemail_provider_creds(auth, company_id)
    try:
        result = voicedrop_request_json(
            method="POST",
            path="/v1/sender-numbers/verify",
            api_key=creds["api_key"],
            json_payload={"phone_number": data.phone_number, "code": data.code},
        )
    except VoiceDropProviderError as exc:
        _raise_provider_http_error("sender_numbers_verify_complete", exc)
    return {"provider": "voicemail_drop", "result": result}


@router.post("/dnc")
async def add_to_dnc(
    data: AddToDncRequest,
    company_id: str | None = Query(None),
    auth: AuthContext = Depends(get_current_auth),
):
    _, _, creds = _resolve_voicemail_provider_creds(auth, company_id)
    try:
        result = voicedrop_add_to_dnc_list(creds["api_key"], phone=data.phone)
    except VoiceDropProviderError as exc:
        _raise_provider_http_error("dnc_add", exc)
    return {"provider": "voicemail_drop", "result": result}


@router.get("/campaigns/{campaign_id}/reports")
async def export_campaign_reports(
    campaign_id: str,
    company_id: str | None = Query(None),
    auth: AuthContext = Depends(get_current_auth),
):
    _, _, creds = _resolve_voicemail_provider_creds(auth, company_id)
    try:
        result = voicedrop_request_json(
            method="GET",
            path=f"/v1/campaigns/{campaign_id}/reports",
            api_key=creds["api_key"],
        )
    except VoiceDropProviderError as exc:
        _raise_provider_http_error("campaign_reports_export", exc)
    return {"provider": "voicemail_drop", "result": result}
