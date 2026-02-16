from __future__ import annotations

import hashlib
import hmac
import json
import logging
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
from src.observability import incr_metric, log_event, persist_metrics_snapshot


router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _request_id(request: Request | None) -> str | None:
    if not request:
        return None
    return getattr(getattr(request, "state", None), "request_id", None)


def _extract_event_type(payload: dict[str, Any]) -> str:
    return (
        payload.get("event")
        or payload.get("event_type")
        or payload.get("type")
        or "unknown"
    )


def _normalize_lob_event_type(value: str | None) -> str:
    if not value:
        return "piece.unknown"
    key = str(value).strip().lower().replace("-", "_")
    if "." in key:
        key = key.split(".")[-1]
    mapping = {
        "created": "piece.created",
        "updated": "piece.updated",
        "processed": "piece.processed",
        "in_transit": "piece.in_transit",
        "in_transit_local": "piece.in_transit",
        "delivered": "piece.delivered",
        "returned": "piece.returned",
        "canceled": "piece.canceled",
        "cancelled": "piece.canceled",
        "re_routed": "piece.re-routed",
        "rerouted": "piece.re-routed",
        "failed": "piece.failed",
    }
    return mapping.get(key, "piece.unknown")


def _normalize_lob_piece_status(normalized_event_type: str) -> str:
    mapping = {
        "piece.created": "queued",
        "piece.updated": "processing",
        "piece.processed": "ready_for_mail",
        "piece.in_transit": "in_transit",
        "piece.delivered": "delivered",
        "piece.returned": "returned",
        "piece.canceled": "canceled",
        "piece.re-routed": "in_transit",
        "piece.failed": "failed",
        "piece.unknown": "unknown",
    }
    return mapping.get(normalized_event_type, "unknown")


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


def _extract_sequence_step_number(payload: dict[str, Any]) -> int | None:
    for key in ("sequence_step_number", "sequenceStepNumber", "step_number", "stepNumber", "seq_number"):
        raw = payload.get(key)
        if raw is None:
            continue
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if value >= 1:
            return value
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


def _compute_lob_event_key(payload: dict[str, Any], raw_body: bytes) -> str:
    for key in ("id", "event_id"):
        if payload.get(key):
            return f"lob:{payload[key]}"

    body = payload.get("body") if isinstance(payload.get("body"), dict) else {}
    resource = body.get("resource") if isinstance(body.get("resource"), dict) else {}
    resource_id = (
        resource.get("id")
        or payload.get("resource_id")
        or payload.get("object_id")
        or payload.get("piece_id")
        or payload.get("mailpiece_id")
    )
    event_type = payload.get("type") or payload.get("event_type") or payload.get("event")
    timestamp = payload.get("date_created") or payload.get("created_at") or payload.get("time")
    if resource_id and event_type and timestamp:
        return f"lob:{resource_id}:{event_type}:{timestamp}"
    return f"lob:{hashlib.sha256(raw_body).hexdigest()}"


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


def _resolve_direct_mail_piece(
    *,
    provider_slug: str,
    piece_external_id: str,
) -> dict[str, Any] | None:
    provider_id = _resolve_provider_id(provider_slug)
    query = supabase.table("company_direct_mail_pieces").select(
        "id, org_id, company_id, provider_id, external_piece_id, piece_type, status"
    ).eq("external_piece_id", piece_external_id).is_("deleted_at", "null")
    if provider_id:
        query = query.eq("provider_id", provider_id)
    result = query.execute()
    if not result.data:
        return None
    return result.data[0]


def _upsert_direct_mail_piece_from_lob_event(
    *,
    piece_external_id: str,
    normalized_event_type: str,
    payload: dict[str, Any],
    piece: dict[str, Any] | None,
) -> dict[str, Any]:
    piece_body = payload.get("body") if isinstance(payload.get("body"), dict) else {}
    resource = piece_body.get("resource") if isinstance(piece_body.get("resource"), dict) else {}
    resource_type = str(resource.get("object") or resource.get("type") or payload.get("resource_type") or "").lower()
    piece_type = "postcard" if "postcard" in resource_type else ("letter" if "letter" in resource_type else None)
    status_value = _normalize_lob_piece_status(normalized_event_type)
    send_date = resource.get("send_date")
    metadata = resource.get("metadata") if isinstance(resource.get("metadata"), dict) else None
    now_iso = _now_iso()

    if piece:
        update_payload = {
            "status": status_value,
            "send_date": send_date,
            "metadata": metadata,
            "raw_payload": payload,
            "updated_at": now_iso,
        }
        supabase.table("company_direct_mail_pieces").update(update_payload).eq(
            "id", piece["id"]
        ).eq("org_id", piece["org_id"]).execute()
        piece.update(update_payload)
        return piece

    if piece_type is None:
        return {}

    provider_id = _resolve_provider_id("lob")
    if not provider_id:
        return {}

    org_id = payload.get("org_id")
    company_id = payload.get("company_id")
    insert_payload = {
        "org_id": org_id,
        "company_id": company_id,
        "provider_id": provider_id,
        "external_piece_id": piece_external_id,
        "piece_type": piece_type,
        "status": status_value,
        "send_date": send_date,
        "metadata": metadata,
        "raw_payload": payload,
        "created_by_user_id": None,
        "created_at": now_iso,
        "updated_at": now_iso,
    }
    # Without tenant context this row cannot be created safely.
    if not org_id or not company_id:
        return {}
    created = supabase.table("company_direct_mail_pieces").insert(insert_payload).execute()
    return created.data[0] if created.data else {}


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


def _replay_webhook_event(
    provider_slug: str,
    event_row: dict[str, Any],
    request_id: str | None = None,
) -> WebhookReplayResponse:
    payload = event_row.get("payload") or {}
    event_type = event_row.get("event_type") or _extract_event_type(payload)
    if provider_slug == "lob":
        piece_external_id = (
            payload.get("resource_id")
            or payload.get("piece_id")
            or payload.get("object_id")
            or (
                payload.get("body", {}).get("resource", {}).get("id")
                if isinstance(payload.get("body"), dict) and isinstance(payload.get("body", {}).get("resource"), dict)
                else None
            )
        )
        if piece_external_id:
            piece = _resolve_direct_mail_piece(provider_slug="lob", piece_external_id=str(piece_external_id))
            _upsert_direct_mail_piece_from_lob_event(
                piece_external_id=str(piece_external_id),
                normalized_event_type=event_type,
                payload=payload,
                piece=piece,
            )
    else:
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
    incr_metric("webhook.replays.processed", provider_slug=provider_slug)
    log_event(
        "webhook_replay_processed",
        request_id=request_id,
        provider_slug=provider_slug,
        event_key=event_row.get("event_key"),
        event_type=event_type,
    )
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
        "sequence_step_number": _extract_sequence_step_number(payload),
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
    req_id = _request_id(request)
    raw_body = await request.body()
    signature = request.headers.get("X-Smartlead-Signature")
    incr_metric("webhook.events.received", provider_slug="smartlead")
    _verify_signature_or_raise(raw_body, signature, settings.smartlead_webhook_secret)

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON payload") from exc

    event_type = _extract_event_type(payload)
    campaign_external_id = _extract_campaign_id(payload)
    event_key = _compute_event_key(payload, raw_body)
    log_event(
        "webhook_received",
        request_id=req_id,
        provider_slug="smartlead",
        event_type=event_type,
        event_key=event_key,
        has_campaign_id=bool(campaign_external_id),
    )

    campaign = _resolve_campaign(campaign_external_id, "smartlead") if campaign_external_id else None
    org_id = campaign["org_id"] if campaign else None
    company_id = campaign["company_id"] if campaign else None

    try:
        _persist_event_or_raise_duplicate("smartlead", event_key, event_type, payload, org_id, company_id)
        _apply_event_to_local_state(campaign=campaign, event_type=event_type, payload=payload)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_200_OK:
            incr_metric("webhook.events.duplicate", provider_slug="smartlead")
            log_event(
                "webhook_duplicate_ignored",
                request_id=req_id,
                provider_slug="smartlead",
                event_type=event_type,
                event_key=event_key,
            )
        else:
            incr_metric("webhook.events.failed", provider_slug="smartlead")
            log_event(
                "webhook_failed",
                level=logging.WARNING,
                request_id=req_id,
                provider_slug="smartlead",
                event_type=event_type,
                event_key=event_key,
                status_code=exc.status_code,
                detail=exc.detail,
            )
        raise
    except Exception as exc:
        incr_metric("webhook.events.failed", provider_slug="smartlead")
        log_event(
            "webhook_failed",
            level=logging.ERROR,
            request_id=req_id,
            provider_slug="smartlead",
            event_type=event_type,
            event_key=event_key,
            error=str(exc),
        )
        raise

    incr_metric("webhook.events.processed", provider_slug="smartlead")
    log_event(
        "webhook_processed",
        request_id=req_id,
        provider_slug="smartlead",
        event_type=event_type,
        event_key=event_key,
        campaign_found=bool(campaign),
    )

    return {"status": "processed", "event_type": event_type, "event_key": event_key}


@router.post("/heyreach")
async def ingest_heyreach_webhook(request: Request):
    req_id = _request_id(request)
    raw_body = await request.body()
    signature = request.headers.get("X-HeyReach-Signature")
    incr_metric("webhook.events.received", provider_slug="heyreach")
    _verify_signature_or_raise(raw_body, signature, settings.heyreach_webhook_secret)

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON payload") from exc

    event_type = _extract_event_type(payload)
    campaign_external_id = _extract_campaign_id(payload)
    event_key = _compute_event_key(payload, raw_body)
    log_event(
        "webhook_received",
        request_id=req_id,
        provider_slug="heyreach",
        event_type=event_type,
        event_key=event_key,
        has_campaign_id=bool(campaign_external_id),
    )

    campaign = _resolve_campaign(campaign_external_id, "heyreach") if campaign_external_id else None
    org_id = campaign["org_id"] if campaign else None
    company_id = campaign["company_id"] if campaign else None

    try:
        _persist_event_or_raise_duplicate("heyreach", event_key, event_type, payload, org_id, company_id)
        _apply_event_to_local_state(campaign=campaign, event_type=event_type, payload=payload)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_200_OK:
            incr_metric("webhook.events.duplicate", provider_slug="heyreach")
            log_event(
                "webhook_duplicate_ignored",
                request_id=req_id,
                provider_slug="heyreach",
                event_type=event_type,
                event_key=event_key,
            )
        else:
            incr_metric("webhook.events.failed", provider_slug="heyreach")
            log_event(
                "webhook_failed",
                level=logging.WARNING,
                request_id=req_id,
                provider_slug="heyreach",
                event_type=event_type,
                event_key=event_key,
                status_code=exc.status_code,
                detail=exc.detail,
            )
        raise
    except Exception as exc:
        incr_metric("webhook.events.failed", provider_slug="heyreach")
        log_event(
            "webhook_failed",
            level=logging.ERROR,
            request_id=req_id,
            provider_slug="heyreach",
            event_type=event_type,
            event_key=event_key,
            error=str(exc),
        )
        raise

    incr_metric("webhook.events.processed", provider_slug="heyreach")
    log_event(
        "webhook_processed",
        request_id=req_id,
        provider_slug="heyreach",
        event_type=event_type,
        event_key=event_key,
        campaign_found=bool(campaign),
    )

    return {"status": "processed", "event_type": event_type, "event_key": event_key}


@router.post("/lob")
async def ingest_lob_webhook(request: Request):
    req_id = _request_id(request)
    raw_body = await request.body()
    signature_mode = "disabled_pending_contract"
    incr_metric("webhook.events.received", provider_slug="lob")

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError:
        payload = {"raw_body": raw_body.decode("utf-8", errors="replace"), "malformed_json": True}

    raw_event_type = _extract_event_type(payload)
    normalized_event_type = _normalize_lob_event_type(raw_event_type)
    event_key = _compute_lob_event_key(payload, raw_body)
    piece_external_id = (
        payload.get("resource_id")
        or payload.get("piece_id")
        or payload.get("object_id")
        or (
            payload.get("body", {}).get("resource", {}).get("id")
            if isinstance(payload.get("body"), dict) and isinstance(payload.get("body", {}).get("resource"), dict)
            else None
        )
    )
    piece = _resolve_direct_mail_piece(provider_slug="lob", piece_external_id=str(piece_external_id)) if piece_external_id else None
    org_id = piece["org_id"] if piece else None
    company_id = piece["company_id"] if piece else None

    # enrich payload with processing metadata for audit/replay
    enriched_payload = dict(payload)
    enriched_payload["_ingestion"] = {
        "provider_slug": "lob",
        "signature_mode": signature_mode,
        "request_headers": {k: v for k, v in request.headers.items()},
        "request_id": req_id,
    }
    if piece_external_id:
        enriched_payload["resource_id"] = str(piece_external_id)

    log_event(
        "webhook_received",
        request_id=req_id,
        provider_slug="lob",
        event_type=normalized_event_type,
        event_key=event_key,
        signature_mode=signature_mode,
        has_piece_id=bool(piece_external_id),
    )

    try:
        _persist_event_or_raise_duplicate("lob", event_key, normalized_event_type, enriched_payload, org_id, company_id)
        if piece_external_id:
            _upsert_direct_mail_piece_from_lob_event(
                piece_external_id=str(piece_external_id),
                normalized_event_type=normalized_event_type,
                payload=enriched_payload,
                piece=piece,
            )
    except HTTPException as exc:
        if exc.status_code == status.HTTP_200_OK:
            incr_metric("webhook.events.duplicate", provider_slug="lob")
            log_event(
                "webhook_duplicate_ignored",
                request_id=req_id,
                provider_slug="lob",
                event_type=normalized_event_type,
                event_key=event_key,
            )
            return {
                "status": "duplicate_ignored",
                "event_type": normalized_event_type,
                "event_key": event_key,
                "signature_mode": signature_mode,
            }
        incr_metric("webhook.events.failed", provider_slug="lob")
        log_event(
            "webhook_failed",
            level=logging.WARNING,
            request_id=req_id,
            provider_slug="lob",
            event_type=normalized_event_type,
            event_key=event_key,
            status_code=exc.status_code,
            detail=exc.detail,
        )
        raise
    except Exception as exc:
        incr_metric("webhook.events.failed", provider_slug="lob")
        log_event(
            "webhook_failed",
            level=logging.ERROR,
            request_id=req_id,
            provider_slug="lob",
            event_type=normalized_event_type,
            event_key=event_key,
            error=str(exc),
        )
        # Persist failed envelope as dead_letter when possible.
        try:
            supabase.table("webhook_events").insert(
                {
                    "provider_slug": "lob",
                    "event_key": f"{event_key}:failure",
                    "event_type": normalized_event_type,
                    "status": "failed",
                    "replay_count": 0,
                    "last_replay_at": None,
                    "last_error": str(exc),
                    "org_id": org_id,
                    "company_id": company_id,
                    "payload": enriched_payload,
                    "processed_at": _now_iso(),
                }
            ).execute()
        except Exception:
            pass
        return {
            "status": "failed_recorded",
            "event_type": normalized_event_type,
            "event_key": event_key,
            "signature_mode": signature_mode,
        }

    incr_metric("webhook.events.processed", provider_slug="lob")
    log_event(
        "webhook_processed",
        request_id=req_id,
        provider_slug="lob",
        event_type=normalized_event_type,
        event_key=event_key,
        signature_mode=signature_mode,
        piece_found=bool(piece),
    )
    return {
        "status": "processed",
        "event_type": normalized_event_type,
        "event_key": event_key,
        "signature_mode": signature_mode,
    }


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
    if provider_slug and provider_slug not in {"smartlead", "heyreach", "lob"}:
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
    result_rows = rows[bounded_offset:bounded_offset + bounded_limit]
    log_event(
        "webhook_events_listed",
        provider_slug=provider_slug,
        event_type=event_type,
        org_id=org_id,
        company_id=company_id,
        returned=len(result_rows),
        limit=bounded_limit,
        offset=bounded_offset,
    )
    return result_rows


@router.post("/replay/{provider_slug}/{event_key}", response_model=WebhookReplayResponse)
async def replay_webhook_event(
    provider_slug: str,
    event_key: str,
    request: Request,
    _ctx: SuperAdminContext = Depends(get_current_super_admin),
):
    if provider_slug not in {"smartlead", "heyreach", "lob"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported provider")
    event_row = _get_webhook_event(provider_slug, event_key)
    if not event_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook event not found")
    req_id = _request_id(request)
    return _replay_webhook_event(provider_slug, event_row, request_id=req_id)


@router.post("/replay-bulk", response_model=WebhookReplayBulkResponse)
async def replay_webhook_events_bulk(
    data: WebhookReplayBulkRequest,
    request: Request,
    _ctx: SuperAdminContext = Depends(get_current_super_admin),
):
    if not data.event_keys:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="event_keys cannot be empty")

    req_id = _request_id(request)
    replayed = 0
    not_found = 0
    results: list[WebhookReplayBulkItem] = []

    for event_key in data.event_keys:
        event_row = _get_webhook_event(data.provider_slug, event_key)
        if not event_row:
            not_found += 1
            results.append(WebhookReplayBulkItem(event_key=event_key, status="not_found", event_type=None))
            continue
        replay_result = _replay_webhook_event(data.provider_slug, event_row, request_id=req_id)
        replayed += 1
        results.append(
            WebhookReplayBulkItem(
                event_key=event_key,
                status="replayed",
                event_type=replay_result.event_type,
            )
        )

    incr_metric("webhook.replays.bulk", provider_slug=data.provider_slug)
    log_event(
        "webhook_bulk_replay_completed",
        request_id=req_id,
        provider_slug=data.provider_slug,
        requested=len(data.event_keys),
        replayed=replayed,
        not_found=not_found,
    )
    persist_metrics_snapshot(
        supabase_client=supabase,
        source="webhook_replay_bulk",
        request_id=req_id,
        reset_after_persist=False,
        export_url=settings.observability_export_url,
        export_bearer_token=settings.observability_export_bearer_token,
        export_timeout_seconds=settings.observability_export_timeout_seconds,
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
    request: Request,
    _ctx: SuperAdminContext = Depends(get_current_super_admin),
):
    req_id = _request_id(request)
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
        replay_result = _replay_webhook_event(data.provider_slug, row, request_id=req_id)
        replayed += 1
        results.append(
            WebhookReplayBulkItem(
                event_key=row["event_key"],
                status="replayed",
                event_type=replay_result.event_type,
            )
        )

    incr_metric("webhook.replays.query", provider_slug=data.provider_slug)
    log_event(
        "webhook_query_replay_completed",
        request_id=req_id,
        provider_slug=data.provider_slug,
        matched=len(selected),
        replayed=replayed,
        limit=data.limit,
    )
    persist_metrics_snapshot(
        supabase_client=supabase,
        source="webhook_replay_query",
        request_id=req_id,
        reset_after_persist=False,
        export_url=settings.observability_export_url,
        export_bearer_token=settings.observability_export_bearer_token,
        export_timeout_seconds=settings.observability_export_timeout_seconds,
    )
    return WebhookReplayQueryResponse(
        provider_slug=data.provider_slug,
        matched=len(selected),
        replayed=replayed,
        results=results,
    )
