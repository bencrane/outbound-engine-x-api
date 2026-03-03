from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.db import supabase
from src.observability import incr_metric, log_event


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _channel_from_provider_slug(provider_slug: str) -> str | None:
    slug = (provider_slug or "").strip().lower()
    if slug in {"smartlead", "emailbison", "instantly"}:
        return "email"
    if slug in {"heyreach"}:
        return "linkedin"
    if slug in {"lob"}:
        return "direct_mail"
    return None


def process_engagement_event(
    *,
    org_id: str,
    campaign_id: str,
    lead_id: str | None,
    event_type: str,
    provider_slug: str,
    payload: dict,
) -> int:
    """
    Check if this event should trigger any progress changes for multi-channel campaigns.
    Returns number of progress rows affected.
    """
    campaign_rows = (
        supabase.table("company_campaigns")
        .select("id, org_id, company_id, campaign_type")
        .eq("id", campaign_id)
        .eq("org_id", org_id)
        .is_("deleted_at", "null")
        .limit(1)
        .execute()
        .data
        or []
    )
    if not campaign_rows:
        return 0

    campaign = campaign_rows[0]
    if campaign.get("campaign_type") != "multi_channel":
        return 0

    progress_row: dict[str, Any] | None = None
    if lead_id:
        progress_rows = (
            supabase.table("campaign_lead_progress")
            .select("id, current_step_order, step_status, next_execute_at")
            .eq("org_id", org_id)
            .eq("company_campaign_id", campaign_id)
            .eq("company_campaign_lead_id", lead_id)
            .limit(1)
            .execute()
            .data
            or []
        )
        progress_row = progress_rows[0] if progress_rows else None

    lowered_event_type = (event_type or "").lower()
    is_reply = ("reply" in lowered_event_type) or ("replied" in lowered_event_type)
    affected = 0
    if is_reply and progress_row and progress_row.get("step_status") == "pending":
        updated = (
            supabase.table("campaign_lead_progress")
            .update(
                {
                    "next_execute_at": _now_iso(),
                    "updated_at": _now_iso(),
                }
            )
            .eq("id", progress_row["id"])
            .eq("org_id", org_id)
            .execute()
        )
        affected = len(updated.data or [])

    event_payload = {
        "org_id": org_id,
        "company_id": campaign.get("company_id"),
        "company_campaign_id": campaign_id,
        "company_campaign_lead_id": lead_id,
        "event_type": event_type,
        "channel": _channel_from_provider_slug(provider_slug),
        "provider_slug": provider_slug,
        "step_order": progress_row.get("current_step_order") if progress_row else None,
        "payload": payload,
    }
    supabase.table("campaign_events").insert(event_payload).execute()

    incr_metric(
        "orchestrator.event_bridge.processed",
        event_type=event_type,
        provider_slug=provider_slug,
    )
    log_event(
        "orchestrator_event_bridge_processed",
        org_id=org_id,
        campaign_id=campaign_id,
        lead_id=lead_id,
        event_type=event_type,
        provider_slug=provider_slug,
        affected=affected,
    )
    return affected
