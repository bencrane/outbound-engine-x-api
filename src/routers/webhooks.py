from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from src.auth import SuperAdminContext, get_current_super_admin
from src.config import settings
from src.db import supabase
from src.domain.normalization import (
    normalize_campaign_status,
    normalize_lead_status,
    normalize_message_direction,
)
from src.models.webhooks import (
    WebhookEventListItem,
    WebhookReplayBulkItem,
    WebhookReplayBulkRequest,
    WebhookReplayBulkResponse,
    WebhookReplayQueryRequest,
    WebhookReplayQueryResponse,
    WebhookReplayResponse,
)


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
    campaign_id = payload.get("campaign_id") or payload.get("campaignId")
    if campaign_id is None and isinstance(payload.get("campaign"), dict):
        campaign_id = payload["campaign"].get("id") or payload["campaign"].get("campaignId")
    return str(campaign_id) if campaign_id is not None else None


def _extract_lead_id(payload: dict[str, Any]) -> str | None:
    lead_id = payload.get("lead_id") or payload.get("leadId")
    if lead_id is None and isinstance(payload.get("lead"), dict):
        lead_id = payload["lead"].get("id") or payload["lead"].get("leadId")
    return str(lead_id) if lead_id is not None else None


def _extract_message_id(payload: dict[str, Any]) -> str | None:
    for key in ("message_id", "messageId", "email_stats_id", "id"):
        if payload.get(key) is not None:
            return str(payload[key])
    return None


def _looks_like_campaign_status(value: str | None) -> bool:
    if not value:
        return False
    return str(value).strip().upper() in {
        "DRAFTED",
        "DRAFT",
        "ACTIVE",
        "START",
        "STARTED",
        "RUNNING",
        "PAUSED",
        "PAUSE",
        "STOPPED",
        "STOP",
        "COMPLETED",
        "DONE",
    }


def _looks_like_lead_status(value: str | None) -> bool:
    if not value:
        return False
    return str(value).strip().lower() in {
        "active",
        "paused",
        "pause",
        "unsubscribed",
        "unsubscribe",
        "replied",
        "reply",
        "bounced",
        "bounce",
        "pending",
        "contacted",
        "connected",
        "not_interested",
        "not interested",
    }


def _extract_campaign_status(payload: dict[str, Any]) -> str | None:
    raw_status = payload.get("status")
    status_value = payload.get("campaign_status") or payload.get("campaignStatus")
    if status_value is None and _looks_like_campaign_status(raw_status):
        status_value = raw_status
    return str(status_value) if status_value is not None else None


def _extract_lead_status(payload: dict[str, Any]) -> str | None:
    raw_status = payload.get("status")
    status_value = payload.get("lead_status") or payload.get("leadStatus")
    if status_value is None and _looks_like_lead_status(raw_status):
        status_value = raw_status
    return str(status_value) if status_value is not None else None


def _verify_signature_or_raise(raw_body: bytes, signature_header: str | None, secret: str | None) -> None:
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
    provider_slug: str,
    event_key: str,
    event_type: str,
    payload: dict[str, Any],
    org_id: str | None,
    company_id: str | None,
) -> None:
    try:
        supabase.table("webhook_events").insert(
            {
                "provider_slug": provider_slug,
                "event_key": event_key,
                "event_type": event_type,
                "status": "processed",
                "replay_count": 0,
                "last_replay_at": None,
                "last_error": None,
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


def _resolve_provider_id(provider_slug: str) -> str | None:
    try:
        provider = (
            supabase.table("providers")
            .select("id")
            .eq("slug", provider_slug)
            .execute()
        )
        if provider.data:
            return provider.data[0]["id"]
    except Exception:
        return None
    return None


def _resolve_campaign(campaign_external_id: str, provider_slug: str) -> dict[str, Any] | None:
    provider_id = _resolve_provider_id(provider_slug)
    query = supabase.table("company_campaigns").select(
        "id, org_id, company_id, provider_id, external_campaign_id, status"
    ).eq("external_campaign_id", campaign_external_id).is_("deleted_at", "null")
    if provider_id:
        query = query.eq("provider_id", provider_id)
    campaign = query.execute()
    if not campaign.data:
        return None
    return campaign.data[0]


def _apply_event_to_local_state(
    campaign: dict[str, Any] | None,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    if not campaign:
        return

    lead_external_id = _extract_lead_id(payload)
    campaign_status_value = _extract_campaign_status(payload)
    lead_status_value = _extract_lead_status(payload)

    if campaign_status_value:
        supabase.table("company_campaigns").update(
            {
                "status": normalize_campaign_status(campaign_status_value),
                "raw_payload": payload,
                "updated_at": _now_iso(),
            }
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
            if lead_status_value:
                supabase.table("company_campaign_leads").update(
                    {
                        "status": normalize_lead_status(lead_status_value),
                        "raw_payload": payload,
                        "updated_at": _now_iso(),
                    }
                ).eq("id", local_lead_id).eq("org_id", campaign["org_id"]).execute()

    direction = normalize_message_direction(
        "inbound"
        if ("reply" in event_type.lower() or "replied" in event_type.lower())
        else ("outbound" if ("message" in event_type.lower() or "sent" in event_type.lower()) else "unknown")
    )
    _upsert_message(campaign, local_lead_id, payload, direction=direction)


def _get_webhook_event(provider_slug: str, event_key: str) -> dict[str, Any] | None:
    event_result = (
        supabase.table("webhook_events")
        .select("id, provider_slug, event_key, event_type, org_id, company_id, payload, processed_at, created_at")
        .eq("provider_slug", provider_slug)
        .eq("event_key", event_key)
        .execute()
    )
    if not event_result.data:
        return None
    return event_result.data[0]


def _replay_webhook_event(provider_slug: str, event_row: dict[str, Any]) -> WebhookReplayResponse:
    payload = event_row.get("payload") or {}
    event_type = event_row.get("event_type") or _extract_event_type(payload)
    campaign_external_id = _extract_campaign_id(payload)
    campaign = _resolve_campaign(campaign_external_id, provider_slug) if campaign_external_id else None
    _apply_event_to_local_state(campaign=campaign, event_type=event_type, payload=payload)
    next_replay_count = int(event_row.get("replay_count") or 0) + 1
    now_iso = _now_iso()
    supabase.table("webhook_events").update(
        {
            "processed_at": now_iso,
            "status": "replayed",
            "last_replay_at": now_iso,
            "replay_count": next_replay_count,
            "last_error": None,
        }
    ).eq("id", event_row["id"]).execute()
    return WebhookReplayResponse(
        status="replayed",
        provider_slug=provider_slug,
        event_key=event_row["event_key"],
        event_type=event_type,
    )


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
        "direction": normalize_message_direction(direction),
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
    _verify_signature_or_raise(raw_body, signature, settings.smartlead_webhook_secret)

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON payload") from exc

    event_type = _extract_event_type(payload)
    campaign_external_id = _extract_campaign_id(payload)
    event_key = _compute_event_key(payload, raw_body)

    campaign = _resolve_campaign(campaign_external_id, "smartlead") if campaign_external_id else None
    org_id = campaign["org_id"] if campaign else None
    company_id = campaign["company_id"] if campaign else None

    _persist_event_or_raise_duplicate("smartlead", event_key, event_type, payload, org_id, company_id)
    _apply_event_to_local_state(campaign=campaign, event_type=event_type, payload=payload)

    return {"status": "processed", "event_type": event_type, "event_key": event_key}


@router.post("/heyreach")
async def ingest_heyreach_webhook(request: Request):
    raw_body = await request.body()
    signature = request.headers.get("X-HeyReach-Signature")
    _verify_signature_or_raise(raw_body, signature, settings.heyreach_webhook_secret)

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON payload") from exc

    event_type = _extract_event_type(payload)
    campaign_external_id = _extract_campaign_id(payload)
    event_key = _compute_event_key(payload, raw_body)

    campaign = _resolve_campaign(campaign_external_id, "heyreach") if campaign_external_id else None
    org_id = campaign["org_id"] if campaign else None
    company_id = campaign["company_id"] if campaign else None

    _persist_event_or_raise_duplicate("heyreach", event_key, event_type, payload, org_id, company_id)
    _apply_event_to_local_state(campaign=campaign, event_type=event_type, payload=payload)

    return {"status": "processed", "event_type": event_type, "event_key": event_key}


@router.get("/events", response_model=list[WebhookEventListItem])
async def list_webhook_events(
    provider_slug: str | None = None,
    event_type: str | None = None,
    org_id: str | None = None,
    company_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
    _ctx: SuperAdminContext = Depends(get_current_super_admin),
):
    if provider_slug and provider_slug not in {"smartlead", "heyreach"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported provider")
    bounded_limit = max(1, min(limit, 200))
    bounded_offset = max(0, offset)

    query = supabase.table("webhook_events").select(
        "id, provider_slug, event_key, event_type, status, org_id, company_id, replay_count, last_replay_at, last_error, processed_at, created_at"
    )
    if provider_slug:
        query = query.eq("provider_slug", provider_slug)
    if event_type:
        query = query.eq("event_type", event_type)
    if org_id:
        query = query.eq("org_id", org_id)
    if company_id:
        query = query.eq("company_id", company_id)
    result = query.execute()
    rows = result.data or []
    rows = sorted(rows, key=lambda row: row.get("created_at") or "", reverse=True)
    return rows[bounded_offset:bounded_offset + bounded_limit]


@router.post("/replay/{provider_slug}/{event_key}", response_model=WebhookReplayResponse)
async def replay_webhook_event(
    provider_slug: str,
    event_key: str,
    _ctx: SuperAdminContext = Depends(get_current_super_admin),
):
    if provider_slug not in {"smartlead", "heyreach"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported provider")
    event_row = _get_webhook_event(provider_slug, event_key)
    if not event_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook event not found")
    return _replay_webhook_event(provider_slug, event_row)


@router.post("/replay-bulk", response_model=WebhookReplayBulkResponse)
async def replay_webhook_events_bulk(
    data: WebhookReplayBulkRequest,
    _ctx: SuperAdminContext = Depends(get_current_super_admin),
):
    if not data.event_keys:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="event_keys cannot be empty")

    replayed = 0
    not_found = 0
    results: list[WebhookReplayBulkItem] = []

    for event_key in data.event_keys:
        event_row = _get_webhook_event(data.provider_slug, event_key)
        if not event_row:
            not_found += 1
            results.append(WebhookReplayBulkItem(event_key=event_key, status="not_found", event_type=None))
            continue
        replay_result = _replay_webhook_event(data.provider_slug, event_row)
        replayed += 1
        results.append(
            WebhookReplayBulkItem(
                event_key=event_key,
                status="replayed",
                event_type=replay_result.event_type,
            )
        )

    return WebhookReplayBulkResponse(
        provider_slug=data.provider_slug,
        requested=len(data.event_keys),
        replayed=replayed,
        not_found=not_found,
        results=results,
    )


@router.post("/replay-query", response_model=WebhookReplayQueryResponse)
async def replay_webhook_events_by_query(
    data: WebhookReplayQueryRequest,
    _ctx: SuperAdminContext = Depends(get_current_super_admin),
):
    query = supabase.table("webhook_events").select(
        "id, provider_slug, event_key, event_type, status, org_id, company_id, payload, replay_count, created_at"
    ).eq("provider_slug", data.provider_slug)
    if data.event_type:
        query = query.eq("event_type", data.event_type)
    if data.org_id:
        query = query.eq("org_id", data.org_id)
    if data.company_id:
        query = query.eq("company_id", data.company_id)
    rows = query.execute().data or []

    def _dt(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    filtered: list[dict[str, Any]] = []
    for row in rows:
        created = _dt(row.get("created_at"))
        if data.from_ts and created and created < data.from_ts:
            continue
        if data.to_ts and created and created > data.to_ts:
            continue
        filtered.append(row)
    filtered = sorted(filtered, key=lambda row: row.get("created_at") or "", reverse=True)
    selected = filtered[: data.limit]

    replayed = 0
    results: list[WebhookReplayBulkItem] = []
    for row in selected:
        replay_result = _replay_webhook_event(data.provider_slug, row)
        replayed += 1
        results.append(
            WebhookReplayBulkItem(
                event_key=row["event_key"],
                status="replayed",
                event_type=replay_result.event_type,
            )
        )

    return WebhookReplayQueryResponse(
        provider_slug=data.provider_slug,
        matched=len(selected),
        replayed=replayed,
        results=results,
    )
