from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.auth import AuthContext, get_current_auth
from src.db import supabase
from src.models.analytics import (
    CampaignAnalyticsDashboardItem,
    ClientAnalyticsRollupItem,
    MessageSyncHealthItem,
    ReliabilityAnalyticsResponse,
    ReliabilityByProviderItem,
    SequenceStepPerformanceItem,
)


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
    if auth.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    return company_id


def _get_campaign_for_auth(auth: AuthContext, campaign_id: str) -> dict[str, Any]:
    if not auth.company_id and auth.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    query = (
        supabase.table("company_campaigns")
        .select("id, org_id, company_id, name, status, created_by_user_id, created_at, updated_at")
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


def _activity_candidates_for_campaign(
    campaign: dict[str, Any],
    leads: list[dict[str, Any]],
    messages: list[dict[str, Any]],
) -> list[datetime]:
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
    return activity_candidates


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

        activity_candidates = _activity_candidates_for_campaign(campaign, leads, messages)

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


@router.get("/clients", response_model=list[ClientAnalyticsRollupItem])
async def get_clients_analytics(
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
    campaigns = campaigns_query.execute().data or []

    rollups: dict[str, dict[str, Any]] = {}
    for campaign in campaigns:
        c_id = campaign["company_id"]
        entry = rollups.setdefault(
            c_id,
            {
                "company_id": c_id,
                "campaigns_total": 0,
                "leads_total": 0,
                "outbound_messages_total": 0,
                "replies_total": 0,
                "activity_candidates": [],
            },
        )
        entry["campaigns_total"] += 1

        leads = (
            supabase.table("company_campaign_leads")
            .select("status, updated_at")
            .eq("org_id", auth.org_id)
            .eq("company_campaign_id", campaign["id"])
            .is_("deleted_at", "null")
            .execute()
            .data
            or []
        )
        entry["leads_total"] += len(leads)

        messages_query = (
            supabase.table("company_campaign_messages")
            .select("direction, sent_at, updated_at")
            .eq("org_id", auth.org_id)
            .eq("company_campaign_id", campaign["id"])
            .is_("deleted_at", "null")
        )
        if from_ts:
            messages_query = messages_query.gte("sent_at", from_ts.isoformat())
        if to_ts:
            messages_query = messages_query.lte("sent_at", to_ts.isoformat())
        messages = messages_query.execute().data or []

        entry["replies_total"] += len([m for m in messages if (m.get("direction") or "").lower() == "inbound"])
        entry["outbound_messages_total"] += len([m for m in messages if (m.get("direction") or "").lower() == "outbound"])
        entry["activity_candidates"].extend(_activity_candidates_for_campaign(campaign, leads, messages))

    results: list[ClientAnalyticsRollupItem] = []
    for row in rollups.values():
        outbound_total = row["outbound_messages_total"]
        replies_total = row["replies_total"]
        reply_rate = round((replies_total / outbound_total) * 100, 2) if outbound_total > 0 else 0.0
        results.append(
            ClientAnalyticsRollupItem(
                company_id=row["company_id"],
                campaigns_total=row["campaigns_total"],
                leads_total=row["leads_total"],
                outbound_messages_total=outbound_total,
                replies_total=replies_total,
                reply_rate=reply_rate,
                last_activity_at=max(row["activity_candidates"]) if row["activity_candidates"] else None,
                updated_at=datetime.now(timezone.utc),
            )
        )

    results = sorted(results, key=lambda item: item.company_id)
    return results


@router.get("/reliability", response_model=ReliabilityAnalyticsResponse)
async def get_reliability_analytics(
    company_id: str | None = Query(None),
    provider_slug: str | None = Query(None),
    from_ts: datetime | None = Query(None),
    to_ts: datetime | None = Query(None),
    auth: AuthContext = Depends(get_current_auth),
):
    resolved_company_id = _resolve_company_scope(auth, company_id)
    if provider_slug and provider_slug not in {"smartlead", "heyreach"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported provider")

    query = supabase.table("webhook_events").select(
        "provider_slug, status, replay_count, last_error, created_at, company_id, org_id"
    ).eq("org_id", auth.org_id)
    if resolved_company_id:
        query = query.eq("company_id", resolved_company_id)
    if provider_slug:
        query = query.eq("provider_slug", provider_slug)
    rows = query.execute().data or []

    filtered_rows: list[dict[str, Any]] = []
    for row in rows:
        created = _parse_datetime(row.get("created_at"))
        if from_ts and created and created < from_ts:
            continue
        if to_ts and created and created > to_ts:
            continue
        filtered_rows.append(row)

    grouped: dict[str, dict[str, int]] = {}
    for row in filtered_rows:
        slug = row.get("provider_slug") or "unknown"
        provider_entry = grouped.setdefault(
            slug,
            {
                "events_total": 0,
                "replayed_events_total": 0,
                "replay_count_total": 0,
                "errors_total": 0,
            },
        )
        provider_entry["events_total"] += 1
        if (row.get("status") or "").lower() == "replayed":
            provider_entry["replayed_events_total"] += 1
        provider_entry["replay_count_total"] += int(row.get("replay_count") or 0)
        if row.get("last_error"):
            provider_entry["errors_total"] += 1

    by_provider = [
        ReliabilityByProviderItem(provider_slug=slug, **values)
        for slug, values in sorted(grouped.items())
    ]
    return ReliabilityAnalyticsResponse(
        company_id=resolved_company_id,
        events_total=sum(item.events_total for item in by_provider),
        replayed_events_total=sum(item.replayed_events_total for item in by_provider),
        replay_count_total=sum(item.replay_count_total for item in by_provider),
        errors_total=sum(item.errors_total for item in by_provider),
        by_provider=by_provider,
        from_ts=from_ts,
        to_ts=to_ts,
        updated_at=datetime.now(timezone.utc),
    )


@router.get("/message-sync-health", response_model=list[MessageSyncHealthItem])
async def get_message_sync_health(
    company_id: str | None = Query(None),
    campaign_id: str | None = Query(None),
    message_sync_status: str | None = Query(None),
    auth: AuthContext = Depends(get_current_auth),
):
    resolved_company_id = _resolve_company_scope(auth, company_id)
    query = supabase.table("company_campaigns").select(
        "id, company_id, name, status, provider_id, message_sync_status, last_message_sync_at, last_message_sync_error, updated_at"
    ).eq("org_id", auth.org_id).is_("deleted_at", "null")
    if resolved_company_id:
        query = query.eq("company_id", resolved_company_id)
    if campaign_id:
        query = query.eq("id", campaign_id)
    if message_sync_status:
        query = query.eq("message_sync_status", message_sync_status)
    campaigns = query.execute().data or []

    items: list[MessageSyncHealthItem] = []
    for campaign in campaigns:
        leads = (
            supabase.table("company_campaign_leads")
            .select("id")
            .eq("org_id", auth.org_id)
            .eq("company_campaign_id", campaign["id"])
            .is_("deleted_at", "null")
            .execute()
            .data
            or []
        )
        messages = (
            supabase.table("company_campaign_messages")
            .select("direction")
            .eq("org_id", auth.org_id)
            .eq("company_campaign_id", campaign["id"])
            .is_("deleted_at", "null")
            .execute()
            .data
            or []
        )
        inbound_total = len([m for m in messages if (m.get("direction") or "").lower() == "inbound"])
        outbound_total = len([m for m in messages if (m.get("direction") or "").lower() == "outbound"])
        items.append(
            MessageSyncHealthItem(
                company_id=campaign["company_id"],
                campaign_id=campaign["id"],
                campaign_name=campaign["name"],
                campaign_status=campaign["status"],
                provider_id=campaign["provider_id"],
                message_sync_status=campaign.get("message_sync_status"),
                last_message_sync_at=_parse_datetime(campaign.get("last_message_sync_at")),
                last_message_sync_error=campaign.get("last_message_sync_error"),
                leads_total=len(leads),
                messages_total=len(messages),
                inbound_total=inbound_total,
                outbound_total=outbound_total,
                updated_at=datetime.now(timezone.utc),
            )
        )

    items = sorted(
        items,
        key=lambda row: (
            row.last_message_sync_at.isoformat() if row.last_message_sync_at else "",
            row.campaign_id,
        ),
        reverse=True,
    )
    return items


@router.get("/campaigns/{campaign_id}/sequence-steps", response_model=list[SequenceStepPerformanceItem])
async def get_campaign_sequence_step_performance(
    campaign_id: str,
    from_ts: datetime | None = Query(None),
    to_ts: datetime | None = Query(None),
    auth: AuthContext = Depends(get_current_auth),
):
    _get_campaign_for_auth(auth, campaign_id)
    query = (
        supabase.table("company_campaign_messages")
        .select(
            "id, company_campaign_lead_id, external_lead_id, direction, sequence_step_number, sent_at, updated_at"
        )
        .eq("org_id", auth.org_id)
        .eq("company_campaign_id", campaign_id)
        .is_("deleted_at", "null")
    )
    if from_ts:
        query = query.gte("sent_at", from_ts.isoformat())
    if to_ts:
        query = query.lte("sent_at", to_ts.isoformat())
    messages = query.execute().data or []

    def _msg_ts(row: dict[str, Any]) -> datetime:
        dt = _parse_datetime(row.get("sent_at")) or _parse_datetime(row.get("updated_at"))
        if dt is None:
            return datetime.min.replace(tzinfo=timezone.utc)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    by_lead: dict[str, list[dict[str, Any]]] = {}
    for row in messages:
        lead_key = row.get("company_campaign_lead_id") or row.get("external_lead_id")
        if not lead_key:
            continue
        by_lead.setdefault(str(lead_key), []).append(row)

    stats: dict[int, dict[str, Any]] = {}

    for lead_messages in by_lead.values():
        ordered = sorted(lead_messages, key=_msg_ts)
        last_outbound_step: int | None = None
        for row in ordered:
            direction = (row.get("direction") or "").lower()
            step_number = row.get("sequence_step_number")
            ts = _msg_ts(row)
            if direction == "outbound" and isinstance(step_number, int) and step_number >= 1:
                step_stats = stats.setdefault(
                    step_number,
                    {
                        "outbound_messages_total": 0,
                        "replies_total": 0,
                        "last_activity_at": ts,
                    },
                )
                step_stats["outbound_messages_total"] += 1
                if ts > step_stats["last_activity_at"]:
                    step_stats["last_activity_at"] = ts
                last_outbound_step = step_number
            elif direction == "inbound" and last_outbound_step is not None:
                step_stats = stats.setdefault(
                    last_outbound_step,
                    {
                        "outbound_messages_total": 0,
                        "replies_total": 0,
                        "last_activity_at": ts,
                    },
                )
                step_stats["replies_total"] += 1
                if ts > step_stats["last_activity_at"]:
                    step_stats["last_activity_at"] = ts

    items: list[SequenceStepPerformanceItem] = []
    for step_number, row in sorted(stats.items()):
        outbound_total = int(row["outbound_messages_total"])
        replies_total = int(row["replies_total"])
        reply_rate = round((replies_total / outbound_total) * 100, 2) if outbound_total > 0 else 0.0
        items.append(
            SequenceStepPerformanceItem(
                campaign_id=campaign_id,
                sequence_step_number=step_number,
                outbound_messages_total=outbound_total,
                replies_total=replies_total,
                reply_rate=reply_rate,
                last_activity_at=row["last_activity_at"],
                updated_at=datetime.now(timezone.utc),
            )
        )
    return items
