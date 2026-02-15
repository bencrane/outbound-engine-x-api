from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from src.config import settings
from src.db import supabase


router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_event_type(payload: dict[str, Any]) -> str:
    return (
        payload.get("event")
        or payload.get("event_type")
        or payload.get("type")
        or "unknown"
    )


def _extract_campaign_id(payload: dict[str, Any]) -> str | None:
    campaign_id = payload.get("campaign_id")
    if campaign_id is None and isinstance(payload.get("campaign"), dict):
        campaign_id = payload["campaign"].get("id")
    return str(campaign_id) if campaign_id is not None else None


def _extract_lead_id(payload: dict[str, Any]) -> str | None:
    lead_id = payload.get("lead_id")
    if lead_id is None and isinstance(payload.get("lead"), dict):
        lead_id = payload["lead"].get("id")
    return str(lead_id) if lead_id is not None else None


def _extract_message_id(payload: dict[str, Any]) -> str | None:
    for key in ("message_id", "email_stats_id", "id"):
        if payload.get(key) is not None:
            return str(payload[key])
    return None


def _extract_status(payload: dict[str, Any]) -> str | None:
    status_value = payload.get("status") or payload.get("campaign_status") or payload.get("lead_status")
    return str(status_value) if status_value is not None else None


def _verify_signature_or_raise(raw_body: bytes, signature_header: str | None) -> None:
    secret = settings.smartlead_webhook_secret
    if not secret:
        return
    if not signature_header:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing webhook signature")

    computed = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(computed, signature_header):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook signature")


def _compute_event_key(payload: dict[str, Any], raw_body: bytes) -> str:
    explicit = payload.get("event_id") or payload.get("id")
    if explicit is not None:
        return str(explicit)
    return hashlib.sha256(raw_body).hexdigest()


def _persist_event_or_raise_duplicate(
    event_key: str,
    event_type: str,
    payload: dict[str, Any],
    org_id: str | None,
    company_id: str | None,
) -> None:
    try:
        supabase.table("webhook_events").insert(
            {
                "provider_slug": "smartlead",
                "event_key": event_key,
                "event_type": event_type,
                "org_id": org_id,
                "company_id": company_id,
                "payload": payload,
                "processed_at": _now_iso(),
            }
        ).execute()
    except Exception as exc:
        # Supabase/PostgREST returns 409-ish errors on unique violation; treat as duplicate.
        if "duplicate" in str(exc).lower() or "unique" in str(exc).lower():
            raise HTTPException(status_code=status.HTTP_200_OK, detail="Duplicate event ignored")
        raise


def _resolve_campaign(campaign_external_id: str) -> dict[str, Any] | None:
    campaign = supabase.table("company_campaigns").select(
        "id, org_id, company_id, provider_id, external_campaign_id, status"
    ).eq("external_campaign_id", campaign_external_id).is_("deleted_at", "null").execute()
    if not campaign.data:
        return None
    return campaign.data[0]


def _upsert_message(
    campaign: dict[str, Any],
    local_lead_id: str | None,
    payload: dict[str, Any],
    direction: str,
) -> None:
    external_message_id = _extract_message_id(payload)
    if not external_message_id:
        return

    existing = supabase.table("company_campaign_messages").select("id").eq(
        "org_id", campaign["org_id"]
    ).eq("company_campaign_id", campaign["id"]).eq("provider_id", campaign["provider_id"]).eq(
        "external_message_id", external_message_id
    ).is_("deleted_at", "null").execute()

    row = {
        "org_id": campaign["org_id"],
        "company_id": campaign["company_id"],
        "company_campaign_id": campaign["id"],
        "company_campaign_lead_id": local_lead_id,
        "provider_id": campaign["provider_id"],
        "external_message_id": external_message_id,
        "external_lead_id": _extract_lead_id(payload),
        "direction": direction if direction in {"inbound", "outbound"} else "unknown",
        "subject": payload.get("subject"),
        "body": payload.get("email_body") or payload.get("body") or payload.get("message"),
        "sent_at": payload.get("sent_at") or payload.get("created_at"),
        "raw_payload": payload,
        "updated_at": _now_iso(),
    }
    if existing.data:
        supabase.table("company_campaign_messages").update(row).eq(
            "id", existing.data[0]["id"]
        ).eq("org_id", campaign["org_id"]).execute()
    else:
        row["created_at"] = _now_iso()
        supabase.table("company_campaign_messages").insert(row).execute()


@router.post("/smartlead")
async def ingest_smartlead_webhook(request: Request):
    raw_body = await request.body()
    signature = request.headers.get("X-Smartlead-Signature")
    _verify_signature_or_raise(raw_body, signature)

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON payload") from exc

    event_type = _extract_event_type(payload)
    campaign_external_id = _extract_campaign_id(payload)
    lead_external_id = _extract_lead_id(payload)
    event_key = _compute_event_key(payload, raw_body)

    campaign = _resolve_campaign(campaign_external_id) if campaign_external_id else None
    org_id = campaign["org_id"] if campaign else None
    company_id = campaign["company_id"] if campaign else None

    _persist_event_or_raise_duplicate(event_key, event_type, payload, org_id, company_id)

    if campaign:
        status_value = _extract_status(payload)
        if status_value:
            supabase.table("company_campaigns").update(
                {"status": status_value, "raw_payload": payload, "updated_at": _now_iso()}
            ).eq("id", campaign["id"]).eq("org_id", campaign["org_id"]).execute()

        local_lead_id = None
        if lead_external_id:
            lead = supabase.table("company_campaign_leads").select("id").eq(
                "org_id", campaign["org_id"]
            ).eq("company_campaign_id", campaign["id"]).eq(
                "external_lead_id", lead_external_id
            ).is_("deleted_at", "null").execute()
            if lead.data:
                local_lead_id = lead.data[0]["id"]
                if status_value:
                    supabase.table("company_campaign_leads").update(
                        {"status": status_value, "raw_payload": payload, "updated_at": _now_iso()}
                    ).eq("id", local_lead_id).eq("org_id", campaign["org_id"]).execute()

        direction = "inbound" if "reply" in event_type.lower() else (
            "outbound" if "sent" in event_type.lower() else "unknown"
        )
        _upsert_message(campaign, local_lead_id, payload, direction=direction)

    return {"status": "processed", "event_type": event_type, "event_key": event_key}
