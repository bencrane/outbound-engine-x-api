from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.auth import AuthContext, get_current_auth
from src.db import supabase
from src.models.analytics import CampaignAnalyticsDashboardItem


router = APIRouter(prefix="/api/analytics", tags=["analytics"])


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


def _resolve_company_scope(auth: AuthContext, company_id: str | None) -> str | None:
    if auth.company_id:
        if company_id and company_id != auth.company_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")
        return auth.company_id
    if company_id and auth.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    return company_id


@router.get("/campaigns", response_model=list[CampaignAnalyticsDashboardItem])
async def get_campaigns_analytics(
    company_id: str | None = Query(None),
    from_ts: datetime | None = Query(None),
    to_ts: datetime | None = Query(None),
    mine_only: bool = Query(False),
    auth: AuthContext = Depends(get_current_auth),
):
    resolved_company_id = _resolve_company_scope(auth, company_id)

    campaigns_query = supabase.table("company_campaigns").select(
        "id, company_id, name, status, created_by_user_id, created_at, updated_at"
    ).eq("org_id", auth.org_id).is_("deleted_at", "null")
    if resolved_company_id:
        campaigns_query = campaigns_query.eq("company_id", resolved_company_id)
    if mine_only:
        campaigns_query = campaigns_query.eq("created_by_user_id", auth.user_id)
    campaigns_result = campaigns_query.execute()

    items: list[CampaignAnalyticsDashboardItem] = []
    for campaign in campaigns_result.data or []:
        leads_result = supabase.table("company_campaign_leads").select(
            "status, updated_at"
        ).eq("org_id", auth.org_id).eq("company_campaign_id", campaign["id"]).is_("deleted_at", "null").execute()

        messages_query = supabase.table("company_campaign_messages").select(
            "direction, sent_at, updated_at"
        ).eq("org_id", auth.org_id).eq("company_campaign_id", campaign["id"]).is_("deleted_at", "null")
        if from_ts:
            messages_query = messages_query.gte("sent_at", from_ts.isoformat())
        if to_ts:
            messages_query = messages_query.lte("sent_at", to_ts.isoformat())
        messages_result = messages_query.execute()

        leads = leads_result.data or []
        messages = messages_result.data or []

        leads_total = len(leads)
        replies_total = len([row for row in messages if (row.get("direction") or "").lower() == "inbound"])
        outbound_total = len([row for row in messages if (row.get("direction") or "").lower() == "outbound"])
        reply_rate = round((replies_total / outbound_total) * 100, 2) if outbound_total > 0 else 0.0

        activity_candidates: list[datetime] = []
        for value in (campaign.get("updated_at"), campaign.get("created_at")):
            dt = _parse_datetime(value)
            if dt:
                activity_candidates.append(dt)
        for lead in leads:
            dt = _parse_datetime(lead.get("updated_at"))
            if dt:
                activity_candidates.append(dt)
        for msg in messages:
            dt = _parse_datetime(msg.get("sent_at")) or _parse_datetime(msg.get("updated_at"))
            if dt:
                activity_candidates.append(dt)

        items.append(
            CampaignAnalyticsDashboardItem(
                campaign_id=campaign["id"],
                company_id=campaign["company_id"],
                campaign_name=campaign["name"],
                campaign_status=campaign["status"],
                leads_total=leads_total,
                replies_total=replies_total,
                outbound_messages_total=outbound_total,
                reply_rate=reply_rate,
                last_activity_at=max(activity_candidates) if activity_candidates else None,
                updated_at=datetime.now(timezone.utc),
            )
        )

    return items
