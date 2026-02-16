from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.auth import AuthContext, get_current_auth, has_permission
from src.db import supabase
from src.models.analytics import (
    CampaignAnalyticsDashboardItem,
    ClientAnalyticsRollupItem,
    DirectMailAnalyticsResponse,
    DirectMailDailyTrendItem,
    MessageSyncHealthItem,
    DirectMailFunnelItem,
    DirectMailReasonBreakdownItem,
    DirectMailVolumeByTypeStatusItem,
    ReliabilityAnalyticsResponse,
    ReliabilityByProviderItem,
    SequenceStepPerformanceItem,
)
from src.observability import persist_metrics_snapshot
from src.config import settings


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


def _require_analytics_read(auth: AuthContext) -> None:
    if not has_permission(auth, "analytics.read"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission required: analytics.read")


def _resolve_company_scope(auth: AuthContext, company_id: str | None) -> str | None:
    _require_analytics_read(auth)
    if auth.company_id:
        if company_id and company_id != auth.company_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")
        return auth.company_id
    if auth.role != "org_admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    return company_id


def _persist_analytics_snapshot(source: str) -> None:
    persist_metrics_snapshot(
        supabase_client=supabase,
        source=source,
        request_id=None,
        reset_after_persist=False,
        export_url=settings.observability_export_url,
        export_bearer_token=settings.observability_export_bearer_token,
        export_timeout_seconds=settings.observability_export_timeout_seconds,
    )


def _get_campaign_for_auth(auth: AuthContext, campaign_id: str) -> dict[str, Any]:
    _require_analytics_read(auth)
    if not auth.company_id and auth.role != "org_admin":
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
    if provider_slug and provider_slug not in {"smartlead", "heyreach", "emailbison"}:
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


@router.get("/direct-mail", response_model=DirectMailAnalyticsResponse)
async def get_direct_mail_analytics(
    company_id: str | None = Query(None),
    all_companies: bool = Query(False),
    from_ts: datetime | None = Query(None),
    to_ts: datetime | None = Query(None),
    limit: int = Query(50),
    offset: int = Query(0),
    max_rows: int = Query(10000),
    auth: AuthContext = Depends(get_current_auth),
):
    if from_ts and to_ts and from_ts > to_ts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"type": "invalid_filter", "message": "from_ts must be before or equal to to_ts"},
        )
    now = datetime.now(timezone.utc)
    effective_to = to_ts or now
    effective_from = from_ts or (effective_to - timedelta(days=30))
    if (effective_to - effective_from).days > 93:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"type": "invalid_filter", "message": "date range exceeds 93 days"},
        )
    bounded_limit = max(1, min(limit, 200))
    bounded_offset = max(0, offset)
    bounded_max_rows = max(1, min(max_rows, 20000))

    if auth.company_id:
        if company_id and company_id != auth.company_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")
        resolved_company_id = auth.company_id
        resolved_all_companies = False
    else:
        if auth.role != "org_admin":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
        if all_companies and company_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"type": "invalid_filter", "message": "company_id cannot be combined with all_companies=true"},
            )
        resolved_all_companies = all_companies
        resolved_company_id = None if all_companies else company_id

    pieces_query = supabase.table("company_direct_mail_pieces").select(
        "piece_type, status, created_at, updated_at, company_id"
    ).eq("org_id", auth.org_id).is_("deleted_at", "null")
    if resolved_company_id:
        pieces_query = pieces_query.eq("company_id", resolved_company_id)
    piece_rows = pieces_query.execute().data or []
    if len(piece_rows) > bounded_max_rows:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"type": "invalid_filter", "message": f"piece row count exceeds max_rows ({bounded_max_rows})"},
        )

    events_query = supabase.table("webhook_events").select(
        "event_type, status, last_error, created_at, company_id, payload"
    ).eq("provider_slug", "lob").eq("org_id", auth.org_id)
    if resolved_company_id:
        events_query = events_query.eq("company_id", resolved_company_id)
    event_rows = events_query.execute().data or []
    if len(event_rows) > bounded_max_rows:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"type": "invalid_filter", "message": f"event row count exceeds max_rows ({bounded_max_rows})"},
        )

    def _in_window(ts_value: Any) -> bool:
        ts = _parse_datetime(ts_value)
        if not ts:
            return False
        return effective_from <= ts <= effective_to

    piece_rows = [row for row in piece_rows if _in_window(row.get("created_at")) or _in_window(row.get("updated_at"))]
    event_rows = [row for row in event_rows if _in_window(row.get("created_at"))]

    volume_counts: dict[tuple[str, str], int] = {}
    for row in piece_rows:
        piece_type = str(row.get("piece_type") or "unknown")
        status_value = str(row.get("status") or "unknown")
        volume_counts[(piece_type, status_value)] = volume_counts.get((piece_type, status_value), 0) + 1
    volume_items = [
        DirectMailVolumeByTypeStatusItem(piece_type=k[0], status=k[1], count=v)
        for k, v in sorted(volume_counts.items(), key=lambda item: (item[0][0], item[0][1]))
    ]

    status_counts: dict[str, int] = {}
    for row in piece_rows:
        status_value = str(row.get("status") or "unknown")
        status_counts[status_value] = status_counts.get(status_value, 0) + 1
    delivery_funnel = [
        DirectMailFunnelItem(stage="created", count=status_counts.get("queued", 0) + status_counts.get("processing", 0)),
        DirectMailFunnelItem(stage="processed", count=status_counts.get("ready_for_mail", 0)),
        DirectMailFunnelItem(stage="in_transit", count=status_counts.get("in_transit", 0)),
        DirectMailFunnelItem(stage="delivered", count=status_counts.get("delivered", 0)),
        DirectMailFunnelItem(stage="returned", count=status_counts.get("returned", 0)),
        DirectMailFunnelItem(stage="failed", count=status_counts.get("failed", 0)),
    ]

    failure_reasons: dict[str, int] = {}
    for row in event_rows:
        payload = row.get("payload") or {}
        dead_letter = payload.get("_dead_letter") if isinstance(payload, dict) else None
        reason = None
        if isinstance(dead_letter, dict):
            reason = dead_letter.get("reason")
        if not reason:
            ingestion = payload.get("_ingestion") if isinstance(payload, dict) else None
            if isinstance(ingestion, dict):
                signature_reason = ingestion.get("signature_reason")
                if signature_reason and signature_reason not in {"verified", "not_verified"}:
                    reason = f"signature:{signature_reason}"
        if not reason and row.get("last_error"):
            reason = "provider_error"
        if reason:
            failure_reasons[str(reason)] = failure_reasons.get(str(reason), 0) + 1
    reason_items = [
        DirectMailReasonBreakdownItem(reason=key, count=value)
        for key, value in sorted(failure_reasons.items(), key=lambda item: (-item[1], item[0]))
    ]
    reason_items = reason_items[bounded_offset:bounded_offset + bounded_limit]

    bucket_map: dict[str, dict[str, int]] = {}
    day_cursor = effective_from.date()
    end_day = effective_to.date()
    while day_cursor <= end_day:
        bucket_map[day_cursor.isoformat()] = {
            "created": 0,
            "processed": 0,
            "in_transit": 0,
            "delivered": 0,
            "returned": 0,
            "failed": 0,
        }
        day_cursor += timedelta(days=1)
    for row in piece_rows:
        created = _parse_datetime(row.get("created_at"))
        if created:
            day = created.date().isoformat()
            if day in bucket_map:
                bucket_map[day]["created"] += 1
    event_to_stage = {
        "piece.processed": "processed",
        "piece.in_transit": "in_transit",
        "piece.delivered": "delivered",
        "piece.returned": "returned",
        "piece.failed": "failed",
    }
    for row in event_rows:
        created = _parse_datetime(row.get("created_at"))
        if not created:
            continue
        day = created.date().isoformat()
        if day not in bucket_map:
            continue
        stage = event_to_stage.get(str(row.get("event_type") or ""))
        if stage:
            bucket_map[day][stage] += 1
    trend_items = [
        DirectMailDailyTrendItem(day=day, **counts)
        for day, counts in sorted(bucket_map.items())
    ]
    trend_items = trend_items[bounded_offset:bounded_offset + bounded_limit]
    volume_items = volume_items[bounded_offset:bounded_offset + bounded_limit]

    _persist_analytics_snapshot(source="direct_mail_analytics")
    return DirectMailAnalyticsResponse(
        org_id=auth.org_id,
        company_id=resolved_company_id,
        all_companies=resolved_all_companies,
        from_ts=effective_from,
        to_ts=effective_to,
        total_pieces=len(piece_rows),
        volume_by_type_status=volume_items,
        delivery_funnel=delivery_funnel,
        failure_reason_breakdown=reason_items,
        daily_trends=trend_items,
        updated_at=now,
    )
