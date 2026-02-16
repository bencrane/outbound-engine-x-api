from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.auth import AuthContext, get_current_auth
from src.db import supabase
from src.domain.normalization import normalize_campaign_status, normalize_lead_status
from src.models.leads import CampaignLeadMutationResponse
from src.models.linkedin import (
    LinkedinCampaignActionRequest,
    LinkedinCampaignCreateRequest,
    LinkedinCampaignLeadsAddRequest,
    LinkedinCampaignLeadResponse,
    LinkedinCampaignMetricsResponse,
    LinkedinCampaignResponse,
    LinkedinLeadStatusUpdateRequest,
    LinkedinSendMessageRequest,
)
from src.models.messages import CampaignMessageResponse
from src.providers.heyreach.client import (
    HeyReachProviderError,
    add_campaign_leads as heyreach_add_campaign_leads,
    create_campaign as heyreach_create_campaign,
    get_campaign_leads as heyreach_get_campaign_leads,
    get_campaign_metrics as heyreach_get_campaign_metrics,
    pause_campaign as heyreach_pause_campaign,
    resume_campaign as heyreach_resume_campaign,
    send_message as heyreach_send_message,
    update_lead_status as heyreach_update_lead_status,
)


router = APIRouter(prefix="/api/linkedin/campaigns", tags=["linkedin-campaigns"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _provider_error_status(exc: HeyReachProviderError) -> int:
    return status.HTTP_503_SERVICE_UNAVAILABLE if exc.retryable else status.HTTP_502_BAD_GATEWAY


def _provider_error_detail(prefix: str, exc: HeyReachProviderError) -> str:
    return f"{prefix} [{exc.category}]: {exc}"


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
    result = (
        supabase.table("companies")
        .select("id, org_id")
        .eq("id", company_id)
        .eq("org_id", auth.org_id)
        .is_("deleted_at", "null")
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")
    return result.data[0]


def _get_heyreach_entitlement(org_id: str, company_id: str) -> dict[str, Any]:
    capability = supabase.table("capabilities").select("id").eq("slug", "linkedin_outreach").execute()
    if not capability.data:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Capability not configured")
    capability_id = capability.data[0]["id"]

    provider = (
        supabase.table("providers")
        .select("id, slug")
        .eq("slug", "heyreach")
        .eq("capability_id", capability_id)
        .execute()
    )
    if not provider.data:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Provider not configured")
    provider_id = provider.data[0]["id"]

    entitlement = (
        supabase.table("company_entitlements")
        .select("*")
        .eq("org_id", org_id)
        .eq("company_id", company_id)
        .eq("capability_id", capability_id)
        .is_("deleted_at", "null")
        .execute()
    )
    if not entitlement.data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="LinkedIn outreach entitlement not found for company",
        )

    row = entitlement.data[0]
    if row["provider_id"] != provider_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Company LinkedIn outreach provider is not HeyReach",
        )
    return row


def _get_org_heyreach_api_key(org_id: str) -> str:
    result = supabase.table("organizations").select("provider_configs").eq("id", org_id).is_("deleted_at", "null").execute()
    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    provider_configs = result.data[0].get("provider_configs") or {}
    heyreach = provider_configs.get("heyreach") or {}
    api_key = heyreach.get("api_key")
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing org-level HeyReach API key",
        )
    return api_key


def _get_campaign_for_auth(auth: AuthContext, campaign_id: str) -> dict[str, Any]:
    query = (
        supabase.table("company_campaigns")
        .select("id, org_id, company_id, provider_id, external_campaign_id, name, status, created_by_user_id, created_at, updated_at")
        .eq("id", campaign_id)
        .eq("org_id", auth.org_id)
        .is_("deleted_at", "null")
    )
    if auth.company_id:
        query = query.eq("company_id", auth.company_id)
    result = query.execute()
    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")
    return result.data[0]


def _get_heyreach_provider_id() -> str:
    provider = (
        supabase.table("providers")
        .select("id")
        .eq("slug", "heyreach")
        .execute()
    )
    if not provider.data:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Provider not configured")
    return provider.data[0]["id"]


def _extract_provider_lead(lead: dict[str, Any]) -> dict[str, Any] | None:
    external_id = lead.get("id") or lead.get("leadId")
    if external_id is None:
        return None
    return {
        "external_lead_id": str(external_id),
        "email": lead.get("email"),
        "first_name": lead.get("firstName") or lead.get("first_name"),
        "last_name": lead.get("lastName") or lead.get("last_name"),
        "company_name": lead.get("company"),
        "title": lead.get("position") or lead.get("title"),
        "status": normalize_lead_status(lead.get("status")),
        "raw_payload": lead,
    }


def _upsert_campaign_lead(
    org_id: str,
    company_id: str,
    campaign_id: str,
    provider_id: str,
    parsed: dict[str, Any],
) -> None:
    existing = (
        supabase.table("company_campaign_leads")
        .select("id")
        .eq("org_id", org_id)
        .eq("company_campaign_id", campaign_id)
        .eq("provider_id", provider_id)
        .eq("external_lead_id", parsed["external_lead_id"])
        .is_("deleted_at", "null")
        .execute()
    )
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
        "status": parsed.get("status") or "unknown",
        "raw_payload": parsed.get("raw_payload"),
        "updated_at": _now_iso(),
    }
    if existing.data:
        (
            supabase.table("company_campaign_leads")
            .update(payload)
            .eq("id", existing.data[0]["id"])
            .eq("org_id", org_id)
            .execute()
        )
    else:
        payload["created_at"] = _now_iso()
        supabase.table("company_campaign_leads").insert(payload).execute()


def _get_campaign_lead_for_auth(auth: AuthContext, campaign_id: str, lead_id: str) -> dict[str, Any]:
    _get_campaign_for_auth(auth, campaign_id)
    result = (
        supabase.table("company_campaign_leads")
        .select("id, org_id, company_campaign_id, external_lead_id, status")
        .eq("id", lead_id)
        .eq("org_id", auth.org_id)
        .eq("company_campaign_id", campaign_id)
        .is_("deleted_at", "null")
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")
    return result.data[0]


@router.post("/", response_model=LinkedinCampaignResponse, status_code=status.HTTP_201_CREATED)
async def create_linkedin_campaign(
    data: LinkedinCampaignCreateRequest,
    auth: AuthContext = Depends(get_current_auth),
):
    company_id = _resolve_company_id(auth, data.company_id)
    _get_company(auth, company_id)
    entitlement = _get_heyreach_entitlement(auth.org_id, company_id)
    api_key = _get_org_heyreach_api_key(auth.org_id)

    try:
        provider_campaign = heyreach_create_campaign(
            api_key=api_key,
            name=data.name,
            description=data.description,
            daily_limit=data.daily_limit,
            delay_between_actions=data.delay_between_actions,
        )
    except HeyReachProviderError as exc:
        raise HTTPException(
            status_code=_provider_error_status(exc),
            detail=_provider_error_detail("Campaign create failed", exc),
        ) from exc

    external_campaign_id = provider_campaign.get("id") or provider_campaign.get("campaignId")
    if external_campaign_id is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Campaign create failed: HeyReach did not return campaign id",
        )

    created = supabase.table("company_campaigns").insert(
        {
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
    ).execute()
    return created.data[0]


@router.get("/", response_model=list[LinkedinCampaignResponse])
async def list_linkedin_campaigns(
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
        _get_heyreach_entitlement(auth.org_id, resolved_company_id)
    heyreach_provider_id = _get_heyreach_provider_id()

    query = (
        supabase.table("company_campaigns")
        .select("id, company_id, provider_id, external_campaign_id, name, status, created_by_user_id, created_at, updated_at")
        .eq("org_id", auth.org_id)
        .eq("provider_id", heyreach_provider_id)
        .is_("deleted_at", "null")
    )
    if resolved_company_id:
        query = query.eq("company_id", resolved_company_id)
    if mine_only:
        query = query.eq("created_by_user_id", auth.user_id)
    result = query.execute()
    return result.data


@router.get("/{campaign_id}", response_model=LinkedinCampaignResponse)
async def get_linkedin_campaign(campaign_id: str, auth: AuthContext = Depends(get_current_auth)):
    return _get_campaign_for_auth(auth, campaign_id)


@router.post("/{campaign_id}/action", response_model=LinkedinCampaignResponse)
async def mutate_linkedin_campaign_status(
    campaign_id: str,
    data: LinkedinCampaignActionRequest,
    auth: AuthContext = Depends(get_current_auth),
):
    campaign = _get_campaign_for_auth(auth, campaign_id)
    api_key = _get_org_heyreach_api_key(auth.org_id)
    try:
        if data.action == "pause":
            provider_response = heyreach_pause_campaign(api_key=api_key, campaign_id=campaign["external_campaign_id"])
            next_status = "PAUSED"
        else:
            provider_response = heyreach_resume_campaign(api_key=api_key, campaign_id=campaign["external_campaign_id"])
            next_status = "ACTIVE"
    except HeyReachProviderError as exc:
        raise HTTPException(
            status_code=_provider_error_status(exc),
            detail=_provider_error_detail("Campaign action failed", exc),
        ) from exc

    updated = (
        supabase.table("company_campaigns")
        .update({"status": next_status, "raw_payload": provider_response, "updated_at": _now_iso()})
        .eq("id", campaign_id)
        .eq("org_id", auth.org_id)
        .execute()
    )
    return updated.data[0]


@router.post("/{campaign_id}/leads", response_model=CampaignLeadMutationResponse)
async def add_linkedin_campaign_leads(
    campaign_id: str,
    data: LinkedinCampaignLeadsAddRequest,
    auth: AuthContext = Depends(get_current_auth),
):
    campaign = _get_campaign_for_auth(auth, campaign_id)
    api_key = _get_org_heyreach_api_key(auth.org_id)
    try:
        heyreach_add_campaign_leads(
            api_key=api_key,
            campaign_id=campaign["external_campaign_id"],
            leads=[lead.model_dump(exclude_none=True) for lead in data.leads],
        )
        provider_leads = heyreach_get_campaign_leads(
            api_key=api_key,
            campaign_id=campaign["external_campaign_id"],
            page=1,
            limit=500,
        )
    except HeyReachProviderError as exc:
        raise HTTPException(
            status_code=_provider_error_status(exc),
            detail=_provider_error_detail("Campaign leads add failed", exc),
        ) from exc

    incoming = {lead.email.lower() for lead in data.leads}
    affected = 0
    for lead in provider_leads:
        parsed = _extract_provider_lead(lead)
        if not parsed:
            continue
        email = (parsed.get("email") or "").lower()
        if email and email in incoming:
            _upsert_campaign_lead(
                org_id=auth.org_id,
                company_id=campaign["company_id"],
                campaign_id=campaign_id,
                provider_id=campaign["provider_id"],
                parsed=parsed,
            )
            affected += 1
    return CampaignLeadMutationResponse(campaign_id=campaign_id, affected=affected, status="added")


@router.get("/{campaign_id}/leads", response_model=list[LinkedinCampaignLeadResponse])
async def list_linkedin_campaign_leads(campaign_id: str, auth: AuthContext = Depends(get_current_auth)):
    _get_campaign_for_auth(auth, campaign_id)
    result = (
        supabase.table("company_campaign_leads")
        .select("id, company_campaign_id, external_lead_id, email, first_name, last_name, company_name, title, status, category, updated_at")
        .eq("org_id", auth.org_id)
        .eq("company_campaign_id", campaign_id)
        .is_("deleted_at", "null")
        .execute()
    )
    return result.data


@router.post("/{campaign_id}/leads/{lead_id}/status", response_model=CampaignLeadMutationResponse)
async def update_linkedin_campaign_lead_status(
    campaign_id: str,
    lead_id: str,
    data: LinkedinLeadStatusUpdateRequest,
    auth: AuthContext = Depends(get_current_auth),
):
    lead = _get_campaign_lead_for_auth(auth, campaign_id, lead_id)
    api_key = _get_org_heyreach_api_key(auth.org_id)
    try:
        heyreach_update_lead_status(api_key=api_key, lead_id=lead["external_lead_id"], status_value=data.status)
    except HeyReachProviderError as exc:
        raise HTTPException(
            status_code=_provider_error_status(exc),
            detail=_provider_error_detail("Lead status update failed", exc),
        ) from exc

    normalized = normalize_lead_status(data.status)
    (
        supabase.table("company_campaign_leads")
        .update({"status": normalized, "updated_at": _now_iso()})
        .eq("id", lead_id)
        .eq("org_id", auth.org_id)
        .execute()
    )
    return CampaignLeadMutationResponse(campaign_id=campaign_id, affected=1, status=normalized)


@router.post("/{campaign_id}/leads/{lead_id}/messages", response_model=CampaignMessageResponse)
async def send_linkedin_campaign_message(
    campaign_id: str,
    lead_id: str,
    data: LinkedinSendMessageRequest,
    auth: AuthContext = Depends(get_current_auth),
):
    campaign = _get_campaign_for_auth(auth, campaign_id)
    lead = _get_campaign_lead_for_auth(auth, campaign_id, lead_id)
    api_key = _get_org_heyreach_api_key(auth.org_id)
    try:
        provider = heyreach_send_message(
            api_key=api_key,
            lead_id=lead["external_lead_id"],
            message=data.message,
            template_id=data.template_id,
        )
    except HeyReachProviderError as exc:
        raise HTTPException(
            status_code=_provider_error_status(exc),
            detail=_provider_error_detail("Send message failed", exc),
        ) from exc

    external_message_id = str(provider.get("messageId") or provider.get("id") or f"local-{datetime.now(timezone.utc).timestamp()}")
    row = (
        supabase.table("company_campaign_messages")
        .insert(
            {
                "org_id": auth.org_id,
                "company_id": campaign["company_id"],
                "company_campaign_id": campaign_id,
                "company_campaign_lead_id": lead_id,
                "provider_id": campaign["provider_id"],
                "external_message_id": external_message_id,
                "external_lead_id": lead["external_lead_id"],
                "direction": "outbound",
                "subject": None,
                "body": data.message,
                "sent_at": _now_iso(),
                "raw_payload": provider,
                "updated_at": _now_iso(),
            }
        )
        .execute()
    )
    return row.data[0]


@router.get("/{campaign_id}/metrics", response_model=LinkedinCampaignMetricsResponse)
async def get_linkedin_campaign_metrics(campaign_id: str, auth: AuthContext = Depends(get_current_auth)):
    campaign = _get_campaign_for_auth(auth, campaign_id)
    api_key = _get_org_heyreach_api_key(auth.org_id)
    try:
        raw = heyreach_get_campaign_metrics(api_key=api_key, campaign_id=campaign["external_campaign_id"])
    except HeyReachProviderError as exc:
        raise HTTPException(
            status_code=_provider_error_status(exc),
            detail=_provider_error_detail("Campaign metrics fetch failed", exc),
        ) from exc

    normalized = {
        "total_leads": raw.get("totalLeads"),
        "contacted": raw.get("contacted"),
        "replied": raw.get("replied"),
        "connected": raw.get("connected"),
        "response_rate": raw.get("responseRate"),
        "connection_rate": raw.get("connectionRate"),
    }
    return LinkedinCampaignMetricsResponse(
        campaign_id=campaign_id,
        provider="heyreach",
        provider_campaign_id=campaign["external_campaign_id"],
        normalized=normalized,
        raw=raw,
        fetched_at=datetime.now(timezone.utc),
    )
