from __future__ import annotations

import hmac
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, status

from src.auth import SuperAdminContext, get_current_super_admin
from src.config import settings
from src.db import supabase
from src.domain.normalization import normalize_campaign_status, normalize_lead_status
from src.models.reconciliation import (
    ReconciliationProviderStats,
    ReconciliationRunRequest,
    ReconciliationRunResponse,
)
from src.providers.heyreach.client import (
    HeyReachProviderError,
    get_campaign_leads as heyreach_get_campaign_leads,
    list_campaigns as heyreach_list_campaigns,
)
from src.providers.smartlead.client import (
    SmartleadProviderError,
    get_campaign_leads as smartlead_get_campaign_leads,
    list_campaigns as smartlead_list_campaigns,
)


router = APIRouter(prefix="/api/internal/reconciliation", tags=["internal-reconciliation"])


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now_utc().isoformat()


def _get_org_provider_api_key(org_id: str, provider_slug: str) -> str | None:
    org = (
        supabase.table("organizations")
        .select("provider_configs")
        .eq("id", org_id)
        .is_("deleted_at", "null")
        .execute()
    )
    if not org.data:
        return None
    provider_configs = org.data[0].get("provider_configs") or {}
    provider_config = provider_configs.get(provider_slug) or {}
    return provider_config.get("api_key")


def _extract_campaign(provider_slug: str, campaign: dict[str, Any]) -> dict[str, Any] | None:
    external_id = campaign.get("id") or campaign.get("campaignId") or campaign.get("campaign_id")
    if external_id is None:
        return None
    return {
        "external_campaign_id": str(external_id),
        "name": campaign.get("name") or campaign.get("campaign_name") or f"{provider_slug}_campaign_{external_id}",
        "status": normalize_campaign_status(campaign.get("status")),
        "raw_payload": campaign,
        "client_id": campaign.get("client_id"),
    }


def _extract_lead(lead: dict[str, Any]) -> dict[str, Any] | None:
    external_id = lead.get("id") or lead.get("lead_id") or lead.get("leadId")
    if external_id is None:
        return None
    return {
        "external_lead_id": str(external_id),
        "email": lead.get("email"),
        "first_name": lead.get("first_name") or lead.get("firstName"),
        "last_name": lead.get("last_name") or lead.get("lastName"),
        "company_name": lead.get("company") or lead.get("company_name"),
        "title": lead.get("title") or lead.get("position"),
        "status": normalize_lead_status(lead.get("status")),
        "raw_payload": lead,
    }


@router.post("/campaigns-leads", response_model=ReconciliationRunResponse)
async def reconcile_campaigns_and_leads(
    data: ReconciliationRunRequest,
    _ctx: SuperAdminContext = Depends(get_current_super_admin),
):
    return _run_reconciliation(data)


def _run_reconciliation(data: ReconciliationRunRequest) -> ReconciliationRunResponse:
    started_at = _now_utc()
    provider_slugs = [data.provider_slug] if data.provider_slug else ["smartlead", "heyreach"]
    provider_stats: list[ReconciliationProviderStats] = []

    providers = supabase.table("providers").select("id, slug").execute().data or []
    provider_id_by_slug = {row["slug"]: row["id"] for row in providers}

    for provider_slug in provider_slugs:
        if provider_slug not in provider_id_by_slug:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Provider not configured: {provider_slug}",
            )
        provider_id = provider_id_by_slug[provider_slug]
        stats = ReconciliationProviderStats(
            provider_slug=provider_slug,
            companies_scanned=0,
            campaigns_scanned=0,
            campaigns_created=0,
            campaigns_updated=0,
            leads_scanned=0,
            leads_created=0,
            leads_updated=0,
            errors=[],
        )

        ent_query = (
            supabase.table("company_entitlements")
            .select("id, org_id, company_id, provider_config")
            .eq("provider_id", provider_id)
            .is_("deleted_at", "null")
        )
        if data.org_id:
            ent_query = ent_query.eq("org_id", data.org_id)
        if data.company_id:
            ent_query = ent_query.eq("company_id", data.company_id)
        entitlements = ent_query.execute().data or []

        for entitlement in entitlements:
            stats.companies_scanned += 1
            org_id = entitlement["org_id"]
            company_id = entitlement["company_id"]
            provider_config = entitlement.get("provider_config") or {}
            api_key = _get_org_provider_api_key(org_id, provider_slug)
            if not api_key:
                stats.errors.append(f"{provider_slug}:{org_id}:{company_id}: missing org api key")
                continue

            try:
                if provider_slug == "smartlead":
                    campaigns = smartlead_list_campaigns(api_key=api_key, limit=data.campaign_limit, offset=0)
                    smartlead_client_id = provider_config.get("smartlead_client_id")
                    if smartlead_client_id is not None:
                        campaigns = [
                            row
                            for row in campaigns
                            if row.get("client_id") is None or str(row.get("client_id")) == str(smartlead_client_id)
                        ]
                else:
                    campaigns = heyreach_list_campaigns(api_key=api_key)
                    campaigns = campaigns[: data.campaign_limit]
            except (SmartleadProviderError, HeyReachProviderError) as exc:
                stats.errors.append(f"{provider_slug}:{org_id}:{company_id}: campaign fetch failed: {exc}")
                continue

            for provider_campaign in campaigns:
                parsed_campaign = _extract_campaign(provider_slug, provider_campaign)
                if not parsed_campaign:
                    continue
                stats.campaigns_scanned += 1

                existing_campaign = (
                    supabase.table("company_campaigns")
                    .select("id, status, name")
                    .eq("org_id", org_id)
                    .eq("company_id", company_id)
                    .eq("provider_id", provider_id)
                    .eq("external_campaign_id", parsed_campaign["external_campaign_id"])
                    .is_("deleted_at", "null")
                    .execute()
                ).data

                if existing_campaign:
                    local_campaign = existing_campaign[0]
                    if (
                        local_campaign.get("status") != parsed_campaign["status"]
                        or local_campaign.get("name") != parsed_campaign["name"]
                    ):
                        stats.campaigns_updated += 1
                        if not data.dry_run:
                            (
                                supabase.table("company_campaigns")
                                .update(
                                    {
                                        "status": parsed_campaign["status"],
                                        "name": parsed_campaign["name"],
                                        "raw_payload": parsed_campaign["raw_payload"],
                                        "updated_at": _now_iso(),
                                    }
                                )
                                .eq("id", local_campaign["id"])
                                .eq("org_id", org_id)
                                .execute()
                            )
                    campaign_id = local_campaign["id"]
                else:
                    stats.campaigns_created += 1
                    if data.dry_run:
                        campaign_id = f"dry-run-{provider_slug}-{parsed_campaign['external_campaign_id']}"
                    else:
                        created = (
                            supabase.table("company_campaigns")
                            .insert(
                                {
                                    "org_id": org_id,
                                    "company_id": company_id,
                                    "provider_id": provider_id,
                                    "external_campaign_id": parsed_campaign["external_campaign_id"],
                                    "name": parsed_campaign["name"],
                                    "status": parsed_campaign["status"],
                                    "raw_payload": parsed_campaign["raw_payload"],
                                    "updated_at": _now_iso(),
                                }
                            )
                            .execute()
                        )
                        campaign_id = created.data[0]["id"]

                try:
                    if provider_slug == "smartlead":
                        leads = smartlead_get_campaign_leads(
                            api_key=api_key,
                            campaign_id=parsed_campaign["external_campaign_id"],
                            limit=data.lead_limit,
                            offset=0,
                        )
                    else:
                        leads = heyreach_get_campaign_leads(
                            api_key=api_key,
                            campaign_id=parsed_campaign["external_campaign_id"],
                            page=1,
                            limit=min(data.lead_limit, 1000),
                        )
                except (SmartleadProviderError, HeyReachProviderError) as exc:
                    stats.errors.append(
                        f"{provider_slug}:{org_id}:{company_id}:{parsed_campaign['external_campaign_id']}: lead fetch failed: {exc}"
                    )
                    continue

                for provider_lead in leads:
                    parsed_lead = _extract_lead(provider_lead)
                    if not parsed_lead:
                        continue
                    stats.leads_scanned += 1
                    existing_lead = (
                        supabase.table("company_campaign_leads")
                        .select("id, status, email, first_name, last_name")
                        .eq("org_id", org_id)
                        .eq("company_campaign_id", campaign_id)
                        .eq("provider_id", provider_id)
                        .eq("external_lead_id", parsed_lead["external_lead_id"])
                        .is_("deleted_at", "null")
                        .execute()
                    ).data

                    if existing_lead:
                        local_lead = existing_lead[0]
                        if (
                            local_lead.get("status") != parsed_lead["status"]
                            or local_lead.get("email") != parsed_lead["email"]
                            or local_lead.get("first_name") != parsed_lead["first_name"]
                            or local_lead.get("last_name") != parsed_lead["last_name"]
                        ):
                            stats.leads_updated += 1
                            if not data.dry_run:
                                (
                                    supabase.table("company_campaign_leads")
                                    .update(
                                        {
                                            "email": parsed_lead["email"],
                                            "first_name": parsed_lead["first_name"],
                                            "last_name": parsed_lead["last_name"],
                                            "company_name": parsed_lead["company_name"],
                                            "title": parsed_lead["title"],
                                            "status": parsed_lead["status"],
                                            "raw_payload": parsed_lead["raw_payload"],
                                            "updated_at": _now_iso(),
                                        }
                                    )
                                    .eq("id", local_lead["id"])
                                    .eq("org_id", org_id)
                                    .execute()
                                )
                    else:
                        stats.leads_created += 1
                        if not data.dry_run:
                            supabase.table("company_campaign_leads").insert(
                                {
                                    "org_id": org_id,
                                    "company_id": company_id,
                                    "company_campaign_id": campaign_id,
                                    "provider_id": provider_id,
                                    "external_lead_id": parsed_lead["external_lead_id"],
                                    "email": parsed_lead["email"],
                                    "first_name": parsed_lead["first_name"],
                                    "last_name": parsed_lead["last_name"],
                                    "company_name": parsed_lead["company_name"],
                                    "title": parsed_lead["title"],
                                    "status": parsed_lead["status"],
                                    "raw_payload": parsed_lead["raw_payload"],
                                    "updated_at": _now_iso(),
                                }
                            ).execute()

        provider_stats.append(stats)

    return ReconciliationRunResponse(
        dry_run=data.dry_run,
        started_at=started_at,
        finished_at=_now_utc(),
        providers=provider_stats,
    )


@router.post("/run-scheduled", response_model=ReconciliationRunResponse)
async def run_reconciliation_scheduled(
    data: ReconciliationRunRequest,
    x_internal_scheduler_secret: str | None = Header(default=None),
):
    configured_secret = settings.internal_scheduler_secret
    if not configured_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="internal scheduler secret is not configured",
        )
    if not x_internal_scheduler_secret or not hmac.compare_digest(
        x_internal_scheduler_secret,
        configured_secret,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid scheduler secret",
        )
    return _run_reconciliation(data)
