from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.auth import AuthContext, get_current_auth
from src.db import supabase
from src.models.campaigns import (
    CampaignCreateRequest,
    CampaignResponse,
    CampaignStatusUpdateRequest,
)
from src.models.sequences import CampaignSequenceResponse, CampaignSequenceUpsertRequest
from src.providers.smartlead.client import (
    SmartleadProviderError,
    create_campaign as smartlead_create_campaign,
    get_campaign_sequence as smartlead_get_campaign_sequence,
    save_campaign_sequence as smartlead_save_campaign_sequence,
    update_campaign_status as smartlead_update_campaign_status,
)


router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def _get_company(auth: AuthContext, company_id: str) -> dict[str, Any]:
    result = supabase.table("companies").select("id, org_id").eq(
        "id", company_id
    ).eq("org_id", auth.org_id).is_("deleted_at", "null").execute()
    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")
    return result.data[0]


def _get_smartlead_entitlement(org_id: str, company_id: str) -> dict[str, Any]:
    capability = supabase.table("capabilities").select("id").eq("slug", "email_outreach").execute()
    if not capability.data:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Capability not configured")
    capability_id = capability.data[0]["id"]

    provider = supabase.table("providers").select("id, slug").eq("slug", "smartlead").eq(
        "capability_id", capability_id
    ).execute()
    if not provider.data:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Provider not configured")
    provider_id = provider.data[0]["id"]

    entitlement = supabase.table("company_entitlements").select("*").eq(
        "org_id", org_id
    ).eq("company_id", company_id).eq("capability_id", capability_id).execute()
    if not entitlement.data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email outreach entitlement not found for company",
        )

    row = entitlement.data[0]
    if row["provider_id"] != provider_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Company email outreach provider is not Smartlead",
        )
    return row


def _get_org_smartlead_api_key(org_id: str) -> str:
    result = supabase.table("organizations").select("provider_configs").eq(
        "id", org_id
    ).is_("deleted_at", "null").execute()
    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    provider_configs = result.data[0].get("provider_configs") or {}
    smartlead = provider_configs.get("smartlead") or {}
    api_key = smartlead.get("api_key")
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing org-level Smartlead API key",
        )
    return api_key


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


@router.post("/", response_model=CampaignResponse, status_code=status.HTTP_201_CREATED)
async def create_campaign(
    data: CampaignCreateRequest,
    auth: AuthContext = Depends(get_current_auth),
):
    company_id = _resolve_company_id(auth, data.company_id)
    _get_company(auth, company_id)
    entitlement = _get_smartlead_entitlement(auth.org_id, company_id)

    provider_config = entitlement.get("provider_config") or {}
    smartlead_client_id = provider_config.get("smartlead_client_id")
    if smartlead_client_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Company is not fully provisioned: missing smartlead_client_id",
        )

    api_key = _get_org_smartlead_api_key(auth.org_id)

    try:
        provider_campaign = smartlead_create_campaign(
            api_key=api_key,
            name=data.name,
            client_id=int(smartlead_client_id),
        )
    except SmartleadProviderError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Campaign create failed: {exc}") from exc

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
        "status": provider_campaign.get("status") or "DRAFTED",
        "created_by_user_id": auth.user_id,
        "raw_payload": provider_campaign,
        "updated_at": _now_iso(),
    }
    created = supabase.table("company_campaigns").insert(insert_data).execute()
    return created.data[0]


@router.get("/", response_model=list[CampaignResponse])
async def list_campaigns(
    company_id: str | None = Query(None),
    mine_only: bool = Query(False),
    auth: AuthContext = Depends(get_current_auth),
):
    resolved_company_id = _resolve_company_id(auth, company_id)
    _get_company(auth, resolved_company_id)

    query = supabase.table("company_campaigns").select(
        "id, company_id, provider_id, external_campaign_id, name, status, created_by_user_id, created_at, updated_at"
    ).eq("org_id", auth.org_id).eq("company_id", resolved_company_id).is_("deleted_at", "null")
    if mine_only:
        query = query.eq("created_by_user_id", auth.user_id)
    result = query.execute()
    return result.data


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

    _get_smartlead_entitlement(auth.org_id, campaign["company_id"])
    api_key = _get_org_smartlead_api_key(auth.org_id)

    try:
        provider_response = smartlead_update_campaign_status(
            api_key=api_key,
            campaign_id=campaign["external_campaign_id"],
            status_value=data.status,
        )
    except SmartleadProviderError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Campaign status update failed: {exc}") from exc

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
    _get_smartlead_entitlement(auth.org_id, campaign["company_id"])
    api_key = _get_org_smartlead_api_key(auth.org_id)

    try:
        sequence = smartlead_get_campaign_sequence(
            api_key=api_key,
            campaign_id=campaign["external_campaign_id"],
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
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Sequence fetch failed: {exc}") from exc

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
    _get_smartlead_entitlement(auth.org_id, campaign["company_id"])
    api_key = _get_org_smartlead_api_key(auth.org_id)

    try:
        provider_payload = smartlead_save_campaign_sequence(
            api_key=api_key,
            campaign_id=campaign["external_campaign_id"],
            sequence=data.sequence,
        )
    except SmartleadProviderError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Sequence save failed: {exc}") from exc

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
