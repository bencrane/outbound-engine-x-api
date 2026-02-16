from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.auth import AuthContext, get_current_auth
from src.db import supabase
from src.domain.normalization import (
    normalize_campaign_status,
    normalize_lead_status,
    normalize_message_direction,
)
from src.domain.provider_errors import (
    provider_error_detail,
    provider_error_http_status,
)
from src.models.campaigns import (
    CampaignScheduleResponse,
    CampaignScheduleUpsertRequest,
    CampaignCreateRequest,
    CampaignResponse,
    CampaignStatusUpdateRequest,
)
from src.models.sequences import CampaignSequenceResponse, CampaignSequenceUpsertRequest
from src.models.leads import (
    CampaignLeadsAddRequest,
    CampaignLeadMutationResponse,
    CampaignLeadResponse,
)
from src.models.messages import CampaignMessageResponse, OrgCampaignMessageResponse
from src.models.analytics import (
    CampaignAnalyticsProviderResponse,
    CampaignAnalyticsSummaryResponse,
)
from src.providers.smartlead.client import (
    add_campaign_leads as smartlead_add_campaign_leads,
    get_campaign_leads as smartlead_get_campaign_leads,
    get_campaign_lead_messages as smartlead_get_campaign_lead_messages,
    get_campaign_analytics as smartlead_get_campaign_analytics,
    get_campaign_replies as smartlead_get_campaign_replies,
    pause_campaign_lead as smartlead_pause_campaign_lead,
    resume_campaign_lead as smartlead_resume_campaign_lead,
    SmartleadProviderError,
    create_campaign as smartlead_create_campaign,
    get_campaign_sequence as smartlead_get_campaign_sequence,
    save_campaign_sequence as smartlead_save_campaign_sequence,
    unsubscribe_campaign_lead as smartlead_unsubscribe_campaign_lead,
    update_campaign_status as smartlead_update_campaign_status,
)
from src.providers.emailbison.client import (
    attach_leads_to_campaign as emailbison_attach_leads_to_campaign,
    create_leads_bulk as emailbison_create_leads_bulk,
    create_lead as emailbison_create_lead,
    EmailBisonProviderError,
    create_campaign as emailbison_create_campaign,
    create_campaign_schedule as emailbison_create_campaign_schedule,
    create_campaign_sequence_steps as emailbison_create_campaign_sequence_steps,
    get_campaign_schedule as emailbison_get_campaign_schedule,
    get_campaign_sequence_steps as emailbison_get_campaign_sequence_steps,
    get_campaign_stats as emailbison_get_campaign_stats,
    list_campaign_leads as emailbison_list_campaign_leads,
    list_replies as emailbison_list_replies,
    stop_future_emails_for_leads as emailbison_stop_future_emails_for_leads,
    unsubscribe_lead as emailbison_unsubscribe_lead,
    update_campaign_status as emailbison_update_campaign_status,
)


router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _raise_provider_http_error(
    provider: str,
    operation: str,
    exc: SmartleadProviderError | EmailBisonProviderError,
) -> None:
    raise HTTPException(
        status_code=provider_error_http_status(exc),
        detail=provider_error_detail(provider=provider, operation=operation, exc=exc),
    ) from exc


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _extract_sequence_step_number(payload: dict[str, Any]) -> int | None:
    for key in ("sequence_step_number", "sequenceStepNumber", "step_number", "stepNumber", "seq_number"):
        raw = payload.get(key)
        if raw is None:
            continue
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if value >= 1:
            return value
    return None


def _resolve_company_id(auth: AuthContext, company_id: str | None) -> str:
    if auth.company_id:
        if company_id and company_id != auth.company_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")
        return auth.company_id

    if auth.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    if not company_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="company_id is required for org-level callers",
        )
    return company_id


def _resolve_company_scope(
    auth: AuthContext,
    *,
    company_id: str | None,
    all_companies: bool,
) -> str | None:
    if auth.company_id:
        if all_companies:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="All-companies view is admin only")
        if company_id and company_id != auth.company_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")
        return auth.company_id

    if auth.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")

    if all_companies:
        if company_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="company_id cannot be combined with all_companies=true",
            )
        return None

    if not company_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="company_id is required for org-level callers",
        )
    return company_id


def _get_company(auth: AuthContext, company_id: str) -> dict[str, Any]:
    result = supabase.table("companies").select("id, org_id").eq(
        "id", company_id
    ).eq("org_id", auth.org_id).is_("deleted_at", "null").execute()
    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")
    return result.data[0]


def _get_provider_by_id(provider_id: str) -> dict[str, Any]:
    result = supabase.table("providers").select("id, slug, capability_id").eq("id", provider_id).execute()
    if not result.data:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Provider not configured")
    return result.data[0]


def _get_email_outreach_entitlement(org_id: str, company_id: str) -> dict[str, Any]:
    capability = supabase.table("capabilities").select("id").eq("slug", "email_outreach").execute()
    if not capability.data:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Capability not configured")
    capability_id = capability.data[0]["id"]

    entitlement = supabase.table("company_entitlements").select("*").eq(
        "org_id", org_id
    ).eq("company_id", company_id).eq("capability_id", capability_id).is_("deleted_at", "null").execute()
    if not entitlement.data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email outreach entitlement not found for company",
        )
    return entitlement.data[0]


def _require_smartlead_email_entitlement(org_id: str, company_id: str) -> dict[str, Any]:
    entitlement = _get_email_outreach_entitlement(org_id, company_id)
    provider = _get_provider_by_id(entitlement["provider_id"])
    if provider["slug"] != "smartlead":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Company email outreach provider is not Smartlead",
        )
    return entitlement


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


def _get_campaign_for_auth(auth: AuthContext, campaign_id: str) -> dict[str, Any]:
    query = supabase.table("company_campaigns").select(
        "id, org_id, company_id, provider_id, external_campaign_id, name, status, created_by_user_id, created_at, updated_at"
    ).eq("id", campaign_id).eq("org_id", auth.org_id).is_("deleted_at", "null")
    if auth.company_id:
        query = query.eq("company_id", auth.company_id)
    result = query.execute()
    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")
    return result.data[0]


def _get_campaign_provider_slug(campaign: dict[str, Any]) -> str:
    provider = _get_provider_by_id(campaign["provider_id"])
    return provider["slug"]


def _extract_provider_lead(lead: dict[str, Any]) -> dict[str, Any] | None:
    external_id = lead.get("id") or lead.get("lead_id")
    if external_id is None:
        return None
    return {
        "external_lead_id": str(external_id),
        "email": lead.get("email"),
        "first_name": lead.get("first_name"),
        "last_name": lead.get("last_name"),
        "company_name": lead.get("company") or lead.get("company_name"),
        "title": lead.get("title"),
        "status": normalize_lead_status(lead.get("status")),
        "category": lead.get("category"),
        "raw_payload": lead,
    }


def _upsert_campaign_lead(
    org_id: str,
    company_id: str,
    campaign_id: str,
    provider_id: str,
    parsed: dict[str, Any],
) -> None:
    existing = supabase.table("company_campaign_leads").select("id").eq(
        "org_id", org_id
    ).eq("company_campaign_id", campaign_id).eq("provider_id", provider_id).eq(
        "external_lead_id", parsed["external_lead_id"]
    ).is_("deleted_at", "null").execute()

    payload = {
        "org_id": org_id,
        "company_id": company_id,
        "company_campaign_id": campaign_id,
        "provider_id": provider_id,
        "external_lead_id": parsed["external_lead_id"],
        "email": parsed.get("email"),
        "first_name": parsed.get("first_name"),
        "last_name": parsed.get("last_name"),
        "company_name": parsed.get("company_name"),
        "title": parsed.get("title"),
        "status": normalize_lead_status(parsed.get("status")),
        "category": parsed.get("category"),
        "raw_payload": parsed.get("raw_payload"),
        "updated_at": _now_iso(),
    }

    if existing.data:
        supabase.table("company_campaign_leads").update(payload).eq(
            "id", existing.data[0]["id"]
        ).eq("org_id", org_id).execute()
    else:
        payload["created_at"] = _now_iso()
        supabase.table("company_campaign_leads").insert(payload).execute()


def _extract_provider_message(message: dict[str, Any], default_direction: str = "unknown") -> dict[str, Any] | None:
    external_id = message.get("id") or message.get("email_stats_id") or message.get("message_id")
    if external_id is None:
        return None
    direction = normalize_message_direction(message.get("direction") or default_direction)
    return {
        "external_message_id": str(external_id),
        "external_lead_id": str(message.get("lead_id")) if message.get("lead_id") is not None else None,
        "direction": direction,
        "sequence_step_number": _extract_sequence_step_number(message),
        "subject": message.get("subject"),
        "body": message.get("email_body") or message.get("body") or message.get("message"),
        "sent_at": message.get("sent_at") or message.get("created_at") or message.get("timestamp"),
        "raw_payload": message,
    }


def _upsert_campaign_message(
    org_id: str,
    company_id: str,
    campaign_id: str,
    provider_id: str,
    parsed: dict[str, Any],
    local_lead_id: str | None,
) -> None:
    existing = supabase.table("company_campaign_messages").select("id").eq(
        "org_id", org_id
    ).eq("company_campaign_id", campaign_id).eq("provider_id", provider_id).eq(
        "external_message_id", parsed["external_message_id"]
    ).is_("deleted_at", "null").execute()

    payload = {
        "org_id": org_id,
        "company_id": company_id,
        "company_campaign_id": campaign_id,
        "company_campaign_lead_id": local_lead_id,
        "provider_id": provider_id,
        "external_message_id": parsed["external_message_id"],
        "external_lead_id": parsed.get("external_lead_id"),
        "direction": parsed.get("direction") or "unknown",
        "sequence_step_number": parsed.get("sequence_step_number"),
        "subject": parsed.get("subject"),
        "body": parsed.get("body"),
        "sent_at": parsed.get("sent_at"),
        "raw_payload": parsed.get("raw_payload"),
        "updated_at": _now_iso(),
    }

    if existing.data:
        supabase.table("company_campaign_messages").update(payload).eq(
            "id", existing.data[0]["id"]
        ).eq("org_id", org_id).execute()
    else:
        payload["created_at"] = _now_iso()
        supabase.table("company_campaign_messages").insert(payload).execute()


@router.post("/", response_model=CampaignResponse, status_code=status.HTTP_201_CREATED)
async def create_campaign(
    data: CampaignCreateRequest,
    auth: AuthContext = Depends(get_current_auth),
):
    company_id = _resolve_company_id(auth, data.company_id)
    _get_company(auth, company_id)
    entitlement = _get_email_outreach_entitlement(auth.org_id, company_id)
    provider = _get_provider_by_id(entitlement["provider_id"])

    if provider["slug"] == "smartlead":
        provider_config = entitlement.get("provider_config") or {}
        smartlead_client_id = provider_config.get("smartlead_client_id")
        if smartlead_client_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Company is not fully provisioned: missing smartlead_client_id",
            )
        provider_credentials = _get_org_provider_config(auth.org_id, "smartlead")
        try:
            provider_campaign = smartlead_create_campaign(
                api_key=provider_credentials["api_key"],
                name=data.name,
                client_id=int(smartlead_client_id),
            )
        except SmartleadProviderError as exc:
            _raise_provider_http_error("smartlead", "campaign_create", exc)
    elif provider["slug"] == "emailbison":
        provider_credentials = _get_org_provider_config(auth.org_id, "emailbison")
        try:
            provider_campaign = emailbison_create_campaign(
                api_key=provider_credentials["api_key"],
                instance_url=provider_credentials.get("instance_url"),
                name=data.name,
            )
        except EmailBisonProviderError as exc:
            _raise_provider_http_error("emailbison", "campaign_create", exc)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported email_outreach provider: {provider['slug']}",
        )

    external_campaign_id = provider_campaign.get("id")
    if external_campaign_id is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Campaign create failed: Smartlead did not return campaign id",
        )

    insert_data = {
        "org_id": auth.org_id,
        "company_id": company_id,
        "provider_id": entitlement["provider_id"],
        "external_campaign_id": str(external_campaign_id),
        "name": provider_campaign.get("name") or data.name,
        "status": normalize_campaign_status(provider_campaign.get("status")),
        "created_by_user_id": auth.user_id,
        "raw_payload": provider_campaign,
        "updated_at": _now_iso(),
    }
    created = supabase.table("company_campaigns").insert(insert_data).execute()
    return created.data[0]


@router.get("/", response_model=list[CampaignResponse])
async def list_campaigns(
    company_id: str | None = Query(None),
    all_companies: bool = Query(False),
    mine_only: bool = Query(False),
    auth: AuthContext = Depends(get_current_auth),
):
    resolved_company_id = _resolve_company_scope(
        auth,
        company_id=company_id,
        all_companies=all_companies,
    )
    if resolved_company_id:
        _get_company(auth, resolved_company_id)

    query = supabase.table("company_campaigns").select(
        "id, company_id, provider_id, external_campaign_id, name, status, created_by_user_id, created_at, updated_at"
    ).eq("org_id", auth.org_id).is_("deleted_at", "null")
    if resolved_company_id:
        query = query.eq("company_id", resolved_company_id)
    if mine_only:
        query = query.eq("created_by_user_id", auth.user_id)
    result = query.execute()
    return result.data


@router.get("/messages", response_model=list[OrgCampaignMessageResponse])
async def list_messages_feed(
    company_id: str | None = Query(None),
    all_companies: bool = Query(False),
    campaign_id: str | None = Query(None),
    direction: str | None = Query(None),
    mine_only: bool = Query(False),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(get_current_auth),
):
    resolved_company_id = _resolve_company_scope(
        auth,
        company_id=company_id,
        all_companies=all_companies,
    )
    if resolved_company_id:
        _get_company(auth, resolved_company_id)

    if direction is not None:
        normalized_direction = normalize_message_direction(direction)
    else:
        normalized_direction = None

    campaign_query = supabase.table("company_campaigns").select(
        "id, company_id, created_by_user_id"
    ).eq("org_id", auth.org_id).is_("deleted_at", "null")
    if resolved_company_id:
        campaign_query = campaign_query.eq("company_id", resolved_company_id)
    if campaign_id:
        campaign_query = campaign_query.eq("id", campaign_id)
    if mine_only:
        campaign_query = campaign_query.eq("created_by_user_id", auth.user_id)

    campaigns = campaign_query.execute().data or []
    campaign_map = {row["id"]: row for row in campaigns}
    if not campaign_map:
        return []

    query = supabase.table("company_campaign_messages").select(
        "id, company_id, company_campaign_id, company_campaign_lead_id, external_message_id, direction, sequence_step_number, subject, body, sent_at, updated_at"
    ).eq("org_id", auth.org_id).is_("deleted_at", "null")
    if resolved_company_id:
        query = query.eq("company_id", resolved_company_id)
    if campaign_id:
        query = query.eq("company_campaign_id", campaign_id)
    if normalized_direction:
        query = query.eq("direction", normalized_direction)

    rows = query.execute().data or []
    rows = [row for row in rows if row.get("company_campaign_id") in campaign_map]
    def _message_sort_ts(row: dict[str, Any]) -> float:
        dt = _parse_datetime(row.get("sent_at")) or _parse_datetime(row.get("updated_at"))
        if dt is None:
            return 0.0
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()

    rows = sorted(rows, key=_message_sort_ts, reverse=True)
    return rows[offset : offset + limit]


@router.get("/{campaign_id}", response_model=CampaignResponse)
async def get_campaign(
    campaign_id: str,
    auth: AuthContext = Depends(get_current_auth),
):
    return _get_campaign_for_auth(auth, campaign_id)


@router.post("/{campaign_id}/status", response_model=CampaignResponse)
async def update_campaign_status(
    campaign_id: str,
    data: CampaignStatusUpdateRequest,
    auth: AuthContext = Depends(get_current_auth),
):
    campaign = _get_campaign_for_auth(auth, campaign_id)
    provider_slug = _get_campaign_provider_slug(campaign)
    provider_credentials = _get_org_provider_config(auth.org_id, provider_slug)

    if provider_slug == "smartlead":
        try:
            provider_response = smartlead_update_campaign_status(
                api_key=provider_credentials["api_key"],
                campaign_id=campaign["external_campaign_id"],
                status_value=data.status,
            )
        except SmartleadProviderError as exc:
            _raise_provider_http_error("smartlead", "campaign_status_update", exc)
    elif provider_slug == "emailbison":
        try:
            provider_response = emailbison_update_campaign_status(
                api_key=provider_credentials["api_key"],
                instance_url=provider_credentials.get("instance_url"),
                campaign_id=campaign["external_campaign_id"],
                status_value=data.status,
            )
        except EmailBisonProviderError as exc:
            _raise_provider_http_error("emailbison", "campaign_status_update", exc)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported email_outreach provider: {provider_slug}",
        )

    updated = supabase.table("company_campaigns").update(
        {
            "status": data.status,
            "raw_payload": provider_response,
            "updated_at": _now_iso(),
        }
    ).eq("id", campaign_id).eq("org_id", auth.org_id).execute()
    return updated.data[0]


@router.get("/{campaign_id}/sequence", response_model=CampaignSequenceResponse)
async def get_campaign_sequence(
    campaign_id: str,
    auth: AuthContext = Depends(get_current_auth),
):
    campaign = _get_campaign_for_auth(auth, campaign_id)
    provider_slug = _get_campaign_provider_slug(campaign)
    provider_credentials = _get_org_provider_config(auth.org_id, provider_slug)

    try:
        if provider_slug == "smartlead":
            sequence = smartlead_get_campaign_sequence(
                api_key=provider_credentials["api_key"],
                campaign_id=campaign["external_campaign_id"],
            )
        elif provider_slug == "emailbison":
            sequence = emailbison_get_campaign_sequence_steps(
                api_key=provider_credentials["api_key"],
                instance_url=provider_credentials.get("instance_url"),
                campaign_id=campaign["external_campaign_id"],
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported email_outreach provider: {provider_slug}",
            )
    except SmartleadProviderError as exc:
        # Fallback to latest local snapshot if provider read is unavailable.
        snapshot = supabase.table("company_campaign_sequences").select(
            "version, sequence_payload, updated_at"
        ).eq("org_id", auth.org_id).eq("company_campaign_id", campaign_id).is_("deleted_at", "null").execute()
        if snapshot.data:
            latest = sorted(snapshot.data, key=lambda row: row["version"], reverse=True)[0]
            return CampaignSequenceResponse(
                campaign_id=campaign_id,
                sequence=latest["sequence_payload"],
                source="local_snapshot",
                version=latest["version"],
                updated_at=latest["updated_at"],
            )
        _raise_provider_http_error("smartlead", "campaign_sequence_fetch", exc)
    except EmailBisonProviderError as exc:
        snapshot = supabase.table("company_campaign_sequences").select(
            "version, sequence_payload, updated_at"
        ).eq("org_id", auth.org_id).eq("company_campaign_id", campaign_id).is_("deleted_at", "null").execute()
        if snapshot.data:
            latest = sorted(snapshot.data, key=lambda row: row["version"], reverse=True)[0]
            return CampaignSequenceResponse(
                campaign_id=campaign_id,
                sequence=latest["sequence_payload"],
                source="local_snapshot",
                version=latest["version"],
                updated_at=latest["updated_at"],
            )
        _raise_provider_http_error("emailbison", "campaign_sequence_fetch", exc)

    snapshots = supabase.table("company_campaign_sequences").select(
        "version"
    ).eq("org_id", auth.org_id).eq("company_campaign_id", campaign_id).is_("deleted_at", "null").execute()
    next_version = (max([row["version"] for row in snapshots.data], default=0)) + 1
    supabase.table("company_campaign_sequences").insert(
        {
            "org_id": auth.org_id,
            "company_campaign_id": campaign_id,
            "version": next_version,
            "sequence_payload": sequence,
            "created_by_user_id": auth.user_id,
            "updated_at": _now_iso(),
        }
    ).execute()

    return CampaignSequenceResponse(
        campaign_id=campaign_id,
        sequence=sequence,
        source="provider",
        version=next_version,
        updated_at=datetime.now(timezone.utc),
    )


@router.post("/{campaign_id}/sequence", response_model=CampaignSequenceResponse)
async def save_campaign_sequence(
    campaign_id: str,
    data: CampaignSequenceUpsertRequest,
    auth: AuthContext = Depends(get_current_auth),
):
    campaign = _get_campaign_for_auth(auth, campaign_id)
    provider_slug = _get_campaign_provider_slug(campaign)
    provider_credentials = _get_org_provider_config(auth.org_id, provider_slug)

    try:
        if provider_slug == "smartlead":
            provider_payload = smartlead_save_campaign_sequence(
                api_key=provider_credentials["api_key"],
                campaign_id=campaign["external_campaign_id"],
                sequence=data.sequence,
            )
        elif provider_slug == "emailbison":
            sequence_steps: list[dict[str, Any]] = []
            for idx, step in enumerate(data.sequence, start=1):
                delay_details = step.get("seq_delay_details") or {}
                wait_in_days = delay_details.get("delay_in_days")
                if wait_in_days is None:
                    wait_in_days = step.get("wait_in_days")
                if wait_in_days is None:
                    wait_in_days = 0
                sequence_steps.append(
                    {
                        "email_subject": step.get("subject") or step.get("email_subject") or f"Step {idx}",
                        "email_body": step.get("email_body") or "",
                        "order": step.get("seq_number") or step.get("order") or idx,
                        "wait_in_days": int(wait_in_days),
                        "variant": bool(step.get("variant", False)),
                        "thread_reply": bool(step.get("thread_reply", False)),
                    }
                )
            provider_payload = emailbison_create_campaign_sequence_steps(
                api_key=provider_credentials["api_key"],
                instance_url=provider_credentials.get("instance_url"),
                campaign_id=campaign["external_campaign_id"],
                title=campaign.get("name") or f"Campaign {campaign_id} sequence",
                sequence_steps=sequence_steps,
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported email_outreach provider: {provider_slug}",
            )
    except SmartleadProviderError as exc:
        _raise_provider_http_error("smartlead", "campaign_sequence_save", exc)
    except EmailBisonProviderError as exc:
        _raise_provider_http_error("emailbison", "campaign_sequence_save", exc)

    snapshots = supabase.table("company_campaign_sequences").select(
        "version"
    ).eq("org_id", auth.org_id).eq("company_campaign_id", campaign_id).is_("deleted_at", "null").execute()
    next_version = (max([row["version"] for row in snapshots.data], default=0)) + 1

    created = supabase.table("company_campaign_sequences").insert(
        {
            "org_id": auth.org_id,
            "company_campaign_id": campaign_id,
            "version": next_version,
            "sequence_payload": data.sequence,
            "created_by_user_id": auth.user_id,
            "updated_at": _now_iso(),
        }
    ).execute()

    supabase.table("company_campaigns").update(
        {
            "raw_payload": provider_payload,
            "updated_at": _now_iso(),
        }
    ).eq("id", campaign_id).eq("org_id", auth.org_id).execute()

    row = created.data[0]
    return CampaignSequenceResponse(
        campaign_id=campaign_id,
        sequence=row["sequence_payload"],
        source="provider",
        version=row["version"],
        updated_at=row["updated_at"],
    )


@router.get("/{campaign_id}/schedule", response_model=CampaignScheduleResponse)
async def get_campaign_schedule(
    campaign_id: str,
    auth: AuthContext = Depends(get_current_auth),
):
    campaign = _get_campaign_for_auth(auth, campaign_id)
    provider_slug = _get_campaign_provider_slug(campaign)
    provider_credentials = _get_org_provider_config(auth.org_id, provider_slug)
    try:
        if provider_slug == "emailbison":
            schedule = emailbison_get_campaign_schedule(
                api_key=provider_credentials["api_key"],
                instance_url=provider_credentials.get("instance_url"),
                campaign_id=campaign["external_campaign_id"],
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported email_outreach provider: {provider_slug}",
            )
    except EmailBisonProviderError as exc:
        _raise_provider_http_error("emailbison", "campaign_schedule_fetch", exc)

    return CampaignScheduleResponse(
        campaign_id=campaign_id,
        schedule=schedule,
        source="provider",
        updated_at=datetime.now(timezone.utc),
    )


@router.post("/{campaign_id}/schedule", response_model=CampaignScheduleResponse)
async def save_campaign_schedule(
    campaign_id: str,
    data: CampaignScheduleUpsertRequest,
    auth: AuthContext = Depends(get_current_auth),
):
    campaign = _get_campaign_for_auth(auth, campaign_id)
    provider_slug = _get_campaign_provider_slug(campaign)
    provider_credentials = _get_org_provider_config(auth.org_id, provider_slug)
    try:
        if provider_slug == "emailbison":
            schedule = emailbison_create_campaign_schedule(
                api_key=provider_credentials["api_key"],
                instance_url=provider_credentials.get("instance_url"),
                campaign_id=campaign["external_campaign_id"],
                schedule=data.model_dump(),
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported email_outreach provider: {provider_slug}",
            )
    except EmailBisonProviderError as exc:
        _raise_provider_http_error("emailbison", "campaign_schedule_save", exc)

    return CampaignScheduleResponse(
        campaign_id=campaign_id,
        schedule=schedule,
        source="provider",
        updated_at=datetime.now(timezone.utc),
    )


@router.post("/{campaign_id}/leads", response_model=CampaignLeadMutationResponse)
async def add_campaign_leads(
    campaign_id: str,
    data: CampaignLeadsAddRequest,
    auth: AuthContext = Depends(get_current_auth),
):
    campaign = _get_campaign_for_auth(auth, campaign_id)
    provider_slug = _get_campaign_provider_slug(campaign)
    provider_credentials = _get_org_provider_config(auth.org_id, provider_slug)

    leads_payload = [lead.model_dump(exclude_none=True) for lead in data.leads]
    try:
        if provider_slug == "smartlead":
            smartlead_add_campaign_leads(
                api_key=provider_credentials["api_key"],
                campaign_id=campaign["external_campaign_id"],
                leads=leads_payload,
            )
            provider_leads = smartlead_get_campaign_leads(
                api_key=provider_credentials["api_key"],
                campaign_id=campaign["external_campaign_id"],
                limit=500,
                offset=0,
            )
        elif provider_slug == "emailbison":
            created_lead_ids: list[int] = []
            if len(leads_payload) > 1:
                created_batch = emailbison_create_leads_bulk(
                    api_key=provider_credentials["api_key"],
                    instance_url=provider_credentials.get("instance_url"),
                    leads=leads_payload,
                )
                created_records = created_batch
            else:
                created_records = [
                    emailbison_create_lead(
                        api_key=provider_credentials["api_key"],
                        instance_url=provider_credentials.get("instance_url"),
                        lead=lead_payload,
                    )
                    for lead_payload in leads_payload
                ]

            for created in created_records:
                lead_id = created.get("id")
                if lead_id is None:
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail="Campaign leads add failed: EmailBison lead create missing id",
                    )
                try:
                    created_lead_ids.append(int(lead_id))
                except (TypeError, ValueError):
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail="Campaign leads add failed: EmailBison lead id is not numeric",
                    )
            emailbison_attach_leads_to_campaign(
                api_key=provider_credentials["api_key"],
                instance_url=provider_credentials.get("instance_url"),
                campaign_id=campaign["external_campaign_id"],
                lead_ids=created_lead_ids,
            )
            provider_leads = emailbison_list_campaign_leads(
                api_key=provider_credentials["api_key"],
                instance_url=provider_credentials.get("instance_url"),
                campaign_id=campaign["external_campaign_id"],
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported email_outreach provider: {provider_slug}",
            )
    except SmartleadProviderError as exc:
        _raise_provider_http_error("smartlead", "campaign_leads_add", exc)
    except EmailBisonProviderError as exc:
        _raise_provider_http_error("emailbison", "campaign_leads_add", exc)

    added_emails = {lead.email.lower() for lead in data.leads}
    affected = 0
    for lead in provider_leads:
        parsed = _extract_provider_lead(lead)
        if not parsed:
            continue
        email = (parsed.get("email") or "").lower()
        if email and email in added_emails:
            _upsert_campaign_lead(
                org_id=auth.org_id,
                company_id=campaign["company_id"],
                campaign_id=campaign_id,
                provider_id=campaign["provider_id"],
                parsed=parsed,
            )
            affected += 1

    return CampaignLeadMutationResponse(campaign_id=campaign_id, affected=affected, status="added")


@router.get("/{campaign_id}/leads", response_model=list[CampaignLeadResponse])
async def list_campaign_leads(
    campaign_id: str,
    auth: AuthContext = Depends(get_current_auth),
):
    _get_campaign_for_auth(auth, campaign_id)
    result = supabase.table("company_campaign_leads").select(
        "id, company_campaign_id, external_lead_id, email, first_name, last_name, company_name, title, status, category, updated_at"
    ).eq("org_id", auth.org_id).eq("company_campaign_id", campaign_id).is_("deleted_at", "null").execute()
    return result.data


def _get_campaign_lead_for_auth(auth: AuthContext, campaign_id: str, lead_id: str) -> dict[str, Any]:
    _get_campaign_for_auth(auth, campaign_id)
    query = supabase.table("company_campaign_leads").select(
        "id, org_id, company_campaign_id, external_lead_id, status"
    ).eq("id", lead_id).eq("org_id", auth.org_id).eq("company_campaign_id", campaign_id).is_("deleted_at", "null")
    result = query.execute()
    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")
    return result.data[0]


@router.post("/{campaign_id}/leads/{lead_id}/pause", response_model=CampaignLeadMutationResponse)
async def pause_campaign_lead(
    campaign_id: str,
    lead_id: str,
    auth: AuthContext = Depends(get_current_auth),
):
    campaign = _get_campaign_for_auth(auth, campaign_id)
    lead = _get_campaign_lead_for_auth(auth, campaign_id, lead_id)
    provider_slug = _get_campaign_provider_slug(campaign)
    provider_credentials = _get_org_provider_config(auth.org_id, provider_slug)
    try:
        if provider_slug == "smartlead":
            smartlead_pause_campaign_lead(
                api_key=provider_credentials["api_key"],
                campaign_id=campaign["external_campaign_id"],
                lead_id=lead["external_lead_id"],
            )
        elif provider_slug == "emailbison":
            external_lead_id = int(lead["external_lead_id"])
            emailbison_stop_future_emails_for_leads(
                api_key=provider_credentials["api_key"],
                instance_url=provider_credentials.get("instance_url"),
                campaign_id=campaign["external_campaign_id"],
                lead_ids=[external_lead_id],
            )
            emailbison_unsubscribe_lead(
                api_key=provider_credentials["api_key"],
                instance_url=provider_credentials.get("instance_url"),
                lead_id=external_lead_id,
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported email_outreach provider: {provider_slug}",
            )
    except SmartleadProviderError as exc:
        _raise_provider_http_error("smartlead", "campaign_lead_pause", exc)
    except EmailBisonProviderError as exc:
        _raise_provider_http_error("emailbison", "campaign_lead_pause", exc)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Pause lead failed: non-numeric external lead id for EmailBison",
        )

    supabase.table("company_campaign_leads").update(
        {"status": "paused", "updated_at": _now_iso()}
    ).eq("id", lead_id).eq("org_id", auth.org_id).execute()
    return CampaignLeadMutationResponse(campaign_id=campaign_id, affected=1, status="paused")


@router.post("/{campaign_id}/leads/{lead_id}/resume", response_model=CampaignLeadMutationResponse)
async def resume_campaign_lead(
    campaign_id: str,
    lead_id: str,
    auth: AuthContext = Depends(get_current_auth),
):
    campaign = _get_campaign_for_auth(auth, campaign_id)
    lead = _get_campaign_lead_for_auth(auth, campaign_id, lead_id)
    provider_slug = _get_campaign_provider_slug(campaign)
    provider_credentials = _get_org_provider_config(auth.org_id, provider_slug)
    try:
        if provider_slug == "smartlead":
            smartlead_resume_campaign_lead(
                api_key=provider_credentials["api_key"],
                campaign_id=campaign["external_campaign_id"],
                lead_id=lead["external_lead_id"],
            )
        elif provider_slug == "emailbison":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Resume lead is not supported for EmailBison in Phase 2",
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported email_outreach provider: {provider_slug}",
            )
    except SmartleadProviderError as exc:
        _raise_provider_http_error("smartlead", "campaign_lead_resume", exc)

    supabase.table("company_campaign_leads").update(
        {"status": "active", "updated_at": _now_iso()}
    ).eq("id", lead_id).eq("org_id", auth.org_id).execute()
    return CampaignLeadMutationResponse(campaign_id=campaign_id, affected=1, status="active")


@router.post("/{campaign_id}/leads/{lead_id}/unsubscribe", response_model=CampaignLeadMutationResponse)
async def unsubscribe_campaign_lead(
    campaign_id: str,
    lead_id: str,
    auth: AuthContext = Depends(get_current_auth),
):
    campaign = _get_campaign_for_auth(auth, campaign_id)
    lead = _get_campaign_lead_for_auth(auth, campaign_id, lead_id)
    provider_slug = _get_campaign_provider_slug(campaign)
    provider_credentials = _get_org_provider_config(auth.org_id, provider_slug)
    try:
        if provider_slug == "smartlead":
            smartlead_unsubscribe_campaign_lead(
                api_key=provider_credentials["api_key"],
                campaign_id=campaign["external_campaign_id"],
                lead_id=lead["external_lead_id"],
            )
        elif provider_slug == "emailbison":
            external_lead_id = int(lead["external_lead_id"])
            emailbison_stop_future_emails_for_leads(
                api_key=provider_credentials["api_key"],
                instance_url=provider_credentials.get("instance_url"),
                campaign_id=campaign["external_campaign_id"],
                lead_ids=[external_lead_id],
            )
            emailbison_unsubscribe_lead(
                api_key=provider_credentials["api_key"],
                instance_url=provider_credentials.get("instance_url"),
                lead_id=external_lead_id,
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported email_outreach provider: {provider_slug}",
            )
    except SmartleadProviderError as exc:
        _raise_provider_http_error("smartlead", "campaign_lead_unsubscribe", exc)
    except EmailBisonProviderError as exc:
        _raise_provider_http_error("emailbison", "campaign_lead_unsubscribe", exc)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsubscribe lead failed: non-numeric external lead id for EmailBison",
        )

    supabase.table("company_campaign_leads").update(
        {"status": "unsubscribed", "updated_at": _now_iso()}
    ).eq("id", lead_id).eq("org_id", auth.org_id).execute()
    return CampaignLeadMutationResponse(campaign_id=campaign_id, affected=1, status="unsubscribed")


@router.get("/{campaign_id}/replies", response_model=list[CampaignMessageResponse])
async def list_campaign_replies(
    campaign_id: str,
    auth: AuthContext = Depends(get_current_auth),
):
    campaign = _get_campaign_for_auth(auth, campaign_id)
    provider_slug = _get_campaign_provider_slug(campaign)
    provider_credentials = _get_org_provider_config(auth.org_id, provider_slug)

    try:
        if provider_slug == "smartlead":
            replies = smartlead_get_campaign_replies(
                api_key=provider_credentials["api_key"],
                campaign_id=campaign["external_campaign_id"],
            )
        elif provider_slug == "emailbison":
            replies = emailbison_list_replies(
                api_key=provider_credentials["api_key"],
                instance_url=provider_credentials.get("instance_url"),
                campaign_id=campaign["external_campaign_id"],
            )
        else:
            replies = []

        for item in replies:
            parsed = _extract_provider_message(item, default_direction="inbound")
            if not parsed:
                continue
            local_lead_id = None
            if parsed.get("external_lead_id"):
                lead = supabase.table("company_campaign_leads").select("id").eq(
                    "org_id", auth.org_id
                ).eq("company_campaign_id", campaign_id).eq(
                    "external_lead_id", parsed["external_lead_id"]
                ).is_("deleted_at", "null").execute()
                if lead.data:
                    local_lead_id = lead.data[0]["id"]
            _upsert_campaign_message(
                org_id=auth.org_id,
                company_id=campaign["company_id"],
                campaign_id=campaign_id,
                provider_id=campaign["provider_id"],
                parsed=parsed,
                local_lead_id=local_lead_id,
            )
    except (SmartleadProviderError, EmailBisonProviderError):
        pass

    result = supabase.table("company_campaign_messages").select(
        "id, company_campaign_id, company_campaign_lead_id, external_message_id, direction, sequence_step_number, subject, body, sent_at, updated_at"
    ).eq("org_id", auth.org_id).eq("company_campaign_id", campaign_id).eq("direction", "inbound").is_("deleted_at", "null").execute()
    return result.data


@router.get("/{campaign_id}/leads/{lead_id}/messages", response_model=list[CampaignMessageResponse])
async def list_campaign_lead_messages(
    campaign_id: str,
    lead_id: str,
    auth: AuthContext = Depends(get_current_auth),
):
    campaign = _get_campaign_for_auth(auth, campaign_id)
    lead = _get_campaign_lead_for_auth(auth, campaign_id, lead_id)
    _require_smartlead_email_entitlement(auth.org_id, campaign["company_id"])
    api_key = _get_org_provider_config(auth.org_id, "smartlead")["api_key"]

    try:
        messages = smartlead_get_campaign_lead_messages(
            api_key=api_key,
            campaign_id=campaign["external_campaign_id"],
            lead_id=lead["external_lead_id"],
        )
        for item in messages:
            parsed = _extract_provider_message(item)
            if not parsed:
                continue
            parsed["external_lead_id"] = lead["external_lead_id"]
            _upsert_campaign_message(
                org_id=auth.org_id,
                company_id=campaign["company_id"],
                campaign_id=campaign_id,
                provider_id=campaign["provider_id"],
                parsed=parsed,
                local_lead_id=lead_id,
            )
    except SmartleadProviderError:
        pass

    result = supabase.table("company_campaign_messages").select(
        "id, company_campaign_id, company_campaign_lead_id, external_message_id, direction, sequence_step_number, subject, body, sent_at, updated_at"
    ).eq("org_id", auth.org_id).eq("company_campaign_id", campaign_id).eq(
        "company_campaign_lead_id", lead_id
    ).is_("deleted_at", "null").execute()
    return result.data


@router.get("/{campaign_id}/analytics/summary", response_model=CampaignAnalyticsSummaryResponse)
async def get_campaign_analytics_summary(
    campaign_id: str,
    auth: AuthContext = Depends(get_current_auth),
):
    campaign = _get_campaign_for_auth(auth, campaign_id)

    leads_result = supabase.table("company_campaign_leads").select(
        "status, updated_at"
    ).eq("org_id", auth.org_id).eq("company_campaign_id", campaign_id).is_("deleted_at", "null").execute()
    messages_result = supabase.table("company_campaign_messages").select(
        "direction, sent_at, updated_at"
    ).eq("org_id", auth.org_id).eq("company_campaign_id", campaign_id).is_("deleted_at", "null").execute()

    leads = leads_result.data or []
    messages = messages_result.data or []

    leads_total = len(leads)
    leads_active = len([row for row in leads if (row.get("status") or "").lower() == "active"])
    leads_paused = len([row for row in leads if (row.get("status") or "").lower() == "paused"])
    leads_unsubscribed = len([row for row in leads if (row.get("status") or "").lower() == "unsubscribed"])
    replies_total = len([row for row in messages if (row.get("direction") or "").lower() == "inbound"])
    outbound_total = len([row for row in messages if (row.get("direction") or "").lower() == "outbound"])
    reply_rate = round((replies_total / outbound_total) * 100, 2) if outbound_total > 0 else 0.0

    activity_candidates: list[datetime] = []
    campaign_updated_at = _parse_datetime(campaign.get("updated_at"))
    if campaign_updated_at:
        activity_candidates.append(campaign_updated_at)
    for lead in leads:
        dt = _parse_datetime(lead.get("updated_at"))
        if dt:
            activity_candidates.append(dt)
    for msg in messages:
        dt = _parse_datetime(msg.get("sent_at")) or _parse_datetime(msg.get("updated_at"))
        if dt:
            activity_candidates.append(dt)

    last_activity_at = max(activity_candidates) if activity_candidates else None

    return CampaignAnalyticsSummaryResponse(
        campaign_id=campaign_id,
        leads_total=leads_total,
        leads_active=leads_active,
        leads_paused=leads_paused,
        leads_unsubscribed=leads_unsubscribed,
        replies_total=replies_total,
        outbound_messages_total=outbound_total,
        reply_rate=reply_rate,
        campaign_status=campaign["status"],
        last_activity_at=last_activity_at,
        updated_at=datetime.now(timezone.utc),
    )


@router.get("/{campaign_id}/analytics/provider", response_model=CampaignAnalyticsProviderResponse)
async def get_campaign_analytics_provider(
    campaign_id: str,
    auth: AuthContext = Depends(get_current_auth),
):
    campaign = _get_campaign_for_auth(auth, campaign_id)
    provider_slug = _get_campaign_provider_slug(campaign)
    provider_credentials = _get_org_provider_config(auth.org_id, provider_slug)

    try:
        if provider_slug == "smartlead":
            raw = smartlead_get_campaign_analytics(
                api_key=provider_credentials["api_key"],
                campaign_id=campaign["external_campaign_id"],
            )
        elif provider_slug == "emailbison":
            raw = emailbison_get_campaign_stats(
                api_key=provider_credentials["api_key"],
                instance_url=provider_credentials.get("instance_url"),
                campaign_id=campaign["external_campaign_id"],
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported email_outreach provider: {provider_slug}",
            )
    except SmartleadProviderError as exc:
        _raise_provider_http_error("smartlead", "campaign_analytics_fetch", exc)
    except EmailBisonProviderError as exc:
        _raise_provider_http_error("emailbison", "campaign_analytics_fetch", exc)

    normalized = {
        "sent": raw.get("sent_count") or raw.get("sent") or raw.get("total_sent"),
        "opened": raw.get("open_count") or raw.get("opened") or raw.get("total_opened"),
        "replied": raw.get("reply_count") or raw.get("replied") or raw.get("total_replied"),
        "bounced": raw.get("bounce_count") or raw.get("bounced") or raw.get("total_bounced"),
    }

    return CampaignAnalyticsProviderResponse(
        campaign_id=campaign_id,
        provider=provider_slug,
        provider_campaign_id=campaign["external_campaign_id"],
        normalized=normalized,
        raw=raw,
        fetched_at=datetime.now(timezone.utc),
    )
