from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.auth import AuthContext, get_current_auth, has_permission
from src.db import supabase
from src.domain.provider_errors import provider_error_detail, provider_error_http_status
from src.models.inboxes import (
    InboxHealthcheckResponse,
    InboxResponse,
    InboxSenderEmailDetailResponse,
    InboxSenderEmailUpdateRequest,
    InboxWarmupBulkLimitRequest,
    InboxWarmupBulkToggleRequest,
    InboxWarmupDetailRequest,
    InboxWarmupResponse,
)
from src.providers.emailbison.client import (
    EmailBisonProviderError,
    bulk_check_missing_mx_records as emailbison_bulk_check_missing_mx_records,
    check_sender_email_mx_records as emailbison_check_sender_email_mx_records,
    delete_sender_email as emailbison_delete_sender_email,
    disable_warmup_for_sender_emails as emailbison_disable_warmup_for_sender_emails,
    enable_warmup_for_sender_emails as emailbison_enable_warmup_for_sender_emails,
    get_sender_email as emailbison_get_sender_email,
    get_sender_email_warmup_details as emailbison_get_sender_email_warmup_details,
    update_sender_email as emailbison_update_sender_email,
    update_sender_email_daily_warmup_limits as emailbison_update_sender_email_daily_warmup_limits,
)


router = APIRouter(prefix="/api/inboxes", tags=["inboxes"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_inboxes_read(auth: AuthContext) -> None:
    if not has_permission(auth, "inboxes.read"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission required: inboxes.read")


def _require_inboxes_write(auth: AuthContext) -> None:
    if not has_permission(auth, "inboxes.write"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission required: inboxes.write")


def _raise_provider_http_error(operation: str, exc: EmailBisonProviderError) -> None:
    raise HTTPException(
        status_code=provider_error_http_status(exc),
        detail=provider_error_detail(provider="emailbison", operation=operation, exc=exc),
    ) from exc


def _resolve_company_scope(auth: AuthContext, company_id: str | None, all_companies: bool) -> str | None:
    _require_inboxes_read(auth)
    resolved_company_id: str | None = company_id
    if auth.company_id:
        if all_companies:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="All-companies view is admin only")
        if company_id and company_id != auth.company_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")
        resolved_company_id = auth.company_id
    else:
        if auth.role != "org_admin":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
        if all_companies and company_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="company_id cannot be combined with all_companies=true",
            )
        if not all_companies and not company_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="company_id is required for org-level callers",
            )
    return resolved_company_id


def _verify_company_in_org(org_id: str, company_id: str) -> None:
    company_check = supabase.table("companies").select("id").eq(
        "id", company_id
    ).eq("org_id", org_id).is_("deleted_at", "null").execute()
    if not company_check.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")


def _get_org_provider_config(org_id: str, provider_slug: str) -> dict[str, Any]:
    result = supabase.table("organizations").select("provider_configs").eq(
        "id", org_id
    ).is_("deleted_at", "null").execute()
    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    provider_configs = result.data[0].get("provider_configs") or {}
    provider_config = provider_configs.get(provider_slug) or {}
    api_key = provider_config.get("api_key")
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Missing org-level {provider_slug} API key",
        )
    return {"api_key": api_key, "instance_url": provider_config.get("instance_url")}


def _get_inbox_for_auth(auth: AuthContext, inbox_id: str) -> dict[str, Any]:
    _require_inboxes_read(auth)
    inbox_result = supabase.table("company_inboxes").select("*").eq(
        "id", inbox_id
    ).eq("org_id", auth.org_id).is_("deleted_at", "null").execute()
    if not inbox_result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inbox not found")
    inbox = inbox_result.data[0]
    if auth.company_id and inbox.get("company_id") != auth.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inbox not found")
    provider_result = supabase.table("providers").select("id, slug").eq(
        "id", inbox["provider_id"]
    ).execute()
    if not provider_result.data:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Provider not configured")
    inbox["provider_slug"] = provider_result.data[0]["slug"]
    return inbox


def _get_inboxes_for_auth(auth: AuthContext, inbox_ids: list[str]) -> list[dict[str, Any]]:
    inboxes: list[dict[str, Any]] = []
    for inbox_id in inbox_ids:
        inboxes.append(_get_inbox_for_auth(auth, inbox_id))
    return inboxes


def _sender_email_ids_from_inboxes(inboxes: list[dict[str, Any]], operation: str) -> list[int]:
    sender_ids: list[int] = []
    for inbox in inboxes:
        if inbox.get("provider_slug") != "emailbison":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{operation} unavailable for one or more providers",
            )
        try:
            sender_ids.append(int(inbox["external_account_id"]))
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{operation} failed: non-numeric external account id",
            )
    return sender_ids


@router.get("/", response_model=list[InboxResponse])
async def list_inboxes(
    company_id: str | None = Query(None),
    all_companies: bool = Query(False),
    auth: AuthContext = Depends(get_current_auth),
):
    resolved_company_id = _resolve_company_scope(auth, company_id, all_companies)
    if resolved_company_id:
        _verify_company_in_org(auth.org_id, resolved_company_id)
    query = supabase.table("company_inboxes").select(
        "id, company_id, provider_id, external_account_id, email, display_name, status, warmup_enabled, updated_at"
    ).eq("org_id", auth.org_id).is_("deleted_at", "null")
    if resolved_company_id:
        query = query.eq("company_id", resolved_company_id)
    result = query.execute()
    return result.data


@router.get("/{inbox_id}/sender-email", response_model=InboxSenderEmailDetailResponse)
async def get_inbox_sender_email(
    inbox_id: str,
    auth: AuthContext = Depends(get_current_auth),
):
    inbox = _get_inbox_for_auth(auth, inbox_id)
    if inbox["provider_slug"] != "emailbison":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Sender-email details unavailable for this provider")
    creds = _get_org_provider_config(auth.org_id, "emailbison")
    try:
        sender = emailbison_get_sender_email(
            api_key=creds["api_key"],
            instance_url=creds.get("instance_url"),
            sender_email_id=inbox["external_account_id"],
        )
    except EmailBisonProviderError as exc:
        _raise_provider_http_error("sender_email_get", exc)
    return InboxSenderEmailDetailResponse(inbox_id=inbox_id, provider="email_outreach", sender_email=sender)


@router.patch("/{inbox_id}/sender-email", response_model=InboxSenderEmailDetailResponse)
async def update_inbox_sender_email(
    inbox_id: str,
    data: InboxSenderEmailUpdateRequest,
    auth: AuthContext = Depends(get_current_auth),
):
    _require_inboxes_write(auth)
    inbox = _get_inbox_for_auth(auth, inbox_id)
    if inbox["provider_slug"] != "emailbison":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Sender-email update unavailable for this provider")
    updates = data.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")
    creds = _get_org_provider_config(auth.org_id, "emailbison")
    try:
        sender = emailbison_update_sender_email(
            api_key=creds["api_key"],
            instance_url=creds.get("instance_url"),
            sender_email_id=inbox["external_account_id"],
            updates=updates,
        )
    except EmailBisonProviderError as exc:
        _raise_provider_http_error("sender_email_update", exc)

    local_update: dict[str, Any] = {"updated_at": _now_iso()}
    if sender.get("name"):
        local_update["display_name"] = sender["name"]
    supabase.table("company_inboxes").update(local_update).eq("id", inbox_id).eq("org_id", auth.org_id).execute()
    return InboxSenderEmailDetailResponse(inbox_id=inbox_id, provider="email_outreach", sender_email=sender)


@router.delete("/{inbox_id}/sender-email")
async def delete_inbox_sender_email(
    inbox_id: str,
    auth: AuthContext = Depends(get_current_auth),
):
    _require_inboxes_write(auth)
    inbox = _get_inbox_for_auth(auth, inbox_id)
    if inbox["provider_slug"] != "emailbison":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Sender-email delete unavailable for this provider")
    creds = _get_org_provider_config(auth.org_id, "emailbison")
    try:
        result = emailbison_delete_sender_email(
            api_key=creds["api_key"],
            instance_url=creds.get("instance_url"),
            sender_email_id=inbox["external_account_id"],
        )
    except EmailBisonProviderError as exc:
        _raise_provider_http_error("sender_email_delete", exc)
    supabase.table("company_inboxes").update(
        {"status": "inactive", "updated_at": _now_iso()}
    ).eq("id", inbox_id).eq("org_id", auth.org_id).execute()
    return {"inbox_id": inbox_id, "provider": "email_outreach", "result": result}


@router.post("/{inbox_id}/warmup", response_model=InboxWarmupResponse)
async def get_inbox_warmup(
    inbox_id: str,
    data: InboxWarmupDetailRequest,
    auth: AuthContext = Depends(get_current_auth),
):
    inbox = _get_inbox_for_auth(auth, inbox_id)
    if inbox["provider_slug"] != "emailbison":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Warmup details unavailable for this provider")
    creds = _get_org_provider_config(auth.org_id, "emailbison")
    try:
        warmup = emailbison_get_sender_email_warmup_details(
            api_key=creds["api_key"],
            instance_url=creds.get("instance_url"),
            sender_email_id=inbox["external_account_id"],
            start_date=data.start_date,
            end_date=data.end_date,
        )
    except EmailBisonProviderError as exc:
        _raise_provider_http_error("sender_email_warmup_get", exc)
    return InboxWarmupResponse(inbox_id=inbox_id, provider="email_outreach", warmup=warmup)


@router.patch("/warmup/enable")
async def enable_inbox_warmup(
    data: InboxWarmupBulkToggleRequest,
    auth: AuthContext = Depends(get_current_auth),
):
    _require_inboxes_write(auth)
    inboxes = _get_inboxes_for_auth(auth, data.inbox_ids)
    sender_ids = _sender_email_ids_from_inboxes(inboxes, "Warmup enable")
    creds = _get_org_provider_config(auth.org_id, "emailbison")
    try:
        result = emailbison_enable_warmup_for_sender_emails(
            api_key=creds["api_key"],
            instance_url=creds.get("instance_url"),
            sender_email_ids=sender_ids,
        )
    except EmailBisonProviderError as exc:
        _raise_provider_http_error("sender_email_warmup_enable", exc)
    for inbox in inboxes:
        supabase.table("company_inboxes").update(
            {"warmup_enabled": True, "updated_at": _now_iso()}
        ).eq("id", inbox["id"]).eq("org_id", auth.org_id).execute()
    return {"provider": "email_outreach", "result": result, "affected": len(inboxes)}


@router.patch("/warmup/disable")
async def disable_inbox_warmup(
    data: InboxWarmupBulkToggleRequest,
    auth: AuthContext = Depends(get_current_auth),
):
    _require_inboxes_write(auth)
    inboxes = _get_inboxes_for_auth(auth, data.inbox_ids)
    sender_ids = _sender_email_ids_from_inboxes(inboxes, "Warmup disable")
    creds = _get_org_provider_config(auth.org_id, "emailbison")
    try:
        result = emailbison_disable_warmup_for_sender_emails(
            api_key=creds["api_key"],
            instance_url=creds.get("instance_url"),
            sender_email_ids=sender_ids,
        )
    except EmailBisonProviderError as exc:
        _raise_provider_http_error("sender_email_warmup_disable", exc)
    for inbox in inboxes:
        supabase.table("company_inboxes").update(
            {"warmup_enabled": False, "updated_at": _now_iso()}
        ).eq("id", inbox["id"]).eq("org_id", auth.org_id).execute()
    return {"provider": "email_outreach", "result": result, "affected": len(inboxes)}


@router.patch("/warmup/daily-limits")
async def update_inbox_warmup_daily_limits(
    data: InboxWarmupBulkLimitRequest,
    auth: AuthContext = Depends(get_current_auth),
):
    _require_inboxes_write(auth)
    inboxes = _get_inboxes_for_auth(auth, data.inbox_ids)
    sender_ids = _sender_email_ids_from_inboxes(inboxes, "Warmup limit update")
    creds = _get_org_provider_config(auth.org_id, "emailbison")
    try:
        result = emailbison_update_sender_email_daily_warmup_limits(
            api_key=creds["api_key"],
            instance_url=creds.get("instance_url"),
            sender_email_ids=sender_ids,
            daily_limit=data.daily_limit,
            daily_reply_limit=data.daily_reply_limit,
        )
    except EmailBisonProviderError as exc:
        _raise_provider_http_error("sender_email_warmup_limits_update", exc)
    return {"provider": "email_outreach", "result": result, "affected": len(inboxes)}


@router.post("/{inbox_id}/healthcheck/mx-records", response_model=InboxHealthcheckResponse)
async def check_inbox_mx_records(
    inbox_id: str,
    auth: AuthContext = Depends(get_current_auth),
):
    _require_inboxes_write(auth)
    inbox = _get_inbox_for_auth(auth, inbox_id)
    if inbox["provider_slug"] != "emailbison":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Healthcheck unavailable for this provider")
    creds = _get_org_provider_config(auth.org_id, "emailbison")
    try:
        healthcheck = emailbison_check_sender_email_mx_records(
            api_key=creds["api_key"],
            instance_url=creds.get("instance_url"),
            sender_email_id=inbox["external_account_id"],
        )
    except EmailBisonProviderError as exc:
        _raise_provider_http_error("sender_email_mx_records_check", exc)
    return InboxHealthcheckResponse(inbox_id=inbox_id, provider="email_outreach", healthcheck=healthcheck)


@router.post("/healthcheck/mx-records/bulk-missing")
async def bulk_check_inbox_mx_records_missing(
    auth: AuthContext = Depends(get_current_auth),
):
    _require_inboxes_write(auth)
    if auth.company_id or auth.role != "org_admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    creds = _get_org_provider_config(auth.org_id, "emailbison")
    try:
        result = emailbison_bulk_check_missing_mx_records(
            api_key=creds["api_key"],
            instance_url=creds.get("instance_url"),
        )
    except EmailBisonProviderError as exc:
        _raise_provider_http_error("sender_email_bulk_mx_records_check", exc)
    return {"provider": "email_outreach", "result": result}
