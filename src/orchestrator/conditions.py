from __future__ import annotations

import logging

from src.db import supabase
from src.observability import log_event


def _has_campaign_message(
    *,
    org_id: str,
    campaign_id: str,
    lead_id: str,
    direction: str | None = None,
) -> bool:
    query = (
        supabase.table("company_campaign_messages")
        .select("id")
        .eq("org_id", org_id)
        .eq("company_campaign_id", campaign_id)
        .eq("company_campaign_lead_id", lead_id)
        .is_("deleted_at", "null")
        .limit(1)
    )
    if direction:
        query = query.eq("direction", direction)
    return bool(query.execute().data or [])


def _lead_status_matches(
    *,
    org_id: str,
    campaign_id: str,
    lead_id: str,
    expected_status: str,
) -> bool:
    rows = (
        supabase.table("company_campaign_leads")
        .select("status")
        .eq("org_id", org_id)
        .eq("company_campaign_id", campaign_id)
        .eq("id", lead_id)
        .is_("deleted_at", "null")
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        return False
    return str(rows[0].get("status") or "").lower() == expected_status.lower()


def _prior_step_executed(
    *,
    org_id: str,
    campaign_id: str,
    lead_id: str,
) -> bool:
    rows = (
        supabase.table("campaign_lead_progress")
        .select("current_step_order")
        .eq("org_id", org_id)
        .eq("company_campaign_id", campaign_id)
        .eq("company_campaign_lead_id", lead_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        return False
    return int(rows[0].get("current_step_order") or 0) > 1


def should_skip_step(
    *,
    skip_if: dict | None,
    lead_id: str,
    campaign_id: str,
    org_id: str,
) -> bool:
    if not skip_if:
        return False
    if not isinstance(skip_if, dict):
        log_event(
            "orchestrator_skip_if_unrecognized",
            level=logging.WARNING,
            reason="non_object_skip_if",
            skip_if=skip_if,
            campaign_id=campaign_id,
            lead_id=lead_id,
            org_id=org_id,
        )
        return False

    event_value = skip_if.get("event")
    if event_value == "reply_received":
        return _has_campaign_message(
            org_id=org_id,
            campaign_id=campaign_id,
            lead_id=lead_id,
            direction="inbound",
        )

    if event_value == "message_received":
        direction = skip_if.get("direction")
        if not direction:
            log_event(
                "orchestrator_skip_if_unrecognized",
                level=logging.WARNING,
                reason="message_received_missing_direction",
                skip_if=skip_if,
                campaign_id=campaign_id,
                lead_id=lead_id,
                org_id=org_id,
            )
            return False
        return _has_campaign_message(
            org_id=org_id,
            campaign_id=campaign_id,
            lead_id=lead_id,
            direction=str(direction).lower(),
        )

    lead_status = skip_if.get("lead_status")
    if isinstance(lead_status, str) and lead_status.strip():
        return _lead_status_matches(
            org_id=org_id,
            campaign_id=campaign_id,
            lead_id=lead_id,
            expected_status=lead_status,
        )

    if skip_if.get("prior_step_executed") is True:
        return _prior_step_executed(
            org_id=org_id,
            campaign_id=campaign_id,
            lead_id=lead_id,
        )

    log_event(
        "orchestrator_skip_if_unrecognized",
        level=logging.WARNING,
        reason="unknown_structure",
        skip_if=skip_if,
        campaign_id=campaign_id,
        lead_id=lead_id,
        org_id=org_id,
    )
    return False
