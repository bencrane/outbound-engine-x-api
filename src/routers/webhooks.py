from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status

from src.auth import SuperAdminContext, get_current_super_admin
from src.config import settings
from src.db import supabase
from src.domain.normalization import (
    normalize_campaign_status,
    normalize_lead_status,
    normalize_message_direction,
)
from src.models.webhooks import (
    WebhookDeadLetterDetailResponse,
    WebhookDeadLetterListItem,
    WebhookDeadLetterReplayRequest,
    WebhookDeadLetterReplayResponse,
    WebhookEventListItem,
    WebhookReplayBulkItem,
    WebhookReplayBulkRequest,
    WebhookReplayBulkResponse,
    WebhookReplayQueryRequest,
    WebhookReplayQueryResponse,
    WebhookReplayResponse,
)
from src.observability import incr_metric, log_event, metrics_snapshot, persist_metrics_snapshot


router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])
_LOB_SIGNATURE_MODES = {"permissive_audit", "enforce"}


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


def _allowed_emailbison_origin_hosts() -> set[str]:
    configured = str(settings.emailbison_webhook_allowed_origins or "").split(",")
    allowed: set[str] = set()
    for item in configured:
        value = item.strip()
        if not value:
            continue
        parsed = urlparse(value if "://" in value else f"https://{value}")
        host = (parsed.hostname or value).strip().lower()
        if host:
            allowed.add(host)
    return allowed


def _request_origin_host(request: Request) -> str | None:
    origin = request.headers.get("Origin")
    referer = request.headers.get("Referer")
    forwarded_host = request.headers.get("X-Forwarded-Host")
    host = request.headers.get("Host")
    for candidate in (origin, referer):
        if not candidate:
            continue
        parsed = urlparse(candidate)
        if parsed.hostname:
            return parsed.hostname.lower()
    if forwarded_host:
        return forwarded_host.split(",")[0].strip().lower()
    if host:
        return host.split(":")[0].strip().lower()
    return None


def _is_allowed_origin(origin_host: str, allowlist: set[str]) -> bool:
    for allowed in allowlist:
        if origin_host == allowed or origin_host.endswith(f".{allowed}"):
            return True
    return False


def _verify_emailbison_unsigned_contract_or_raise(*, request: Request, path_token: str) -> str:
    configured_token = settings.emailbison_webhook_path_token
    if not configured_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "type": "webhook_ingress_configuration_error",
                "provider": "emailbison",
                "message": "EMAILBISON_WEBHOOK_PATH_TOKEN is not configured",
            },
        )
    if not hmac.compare_digest(path_token, configured_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "type": "webhook_auth_failed",
                "provider": "emailbison",
                "reason": "invalid_path_token",
                "message": "Invalid EmailBison webhook path token",
            },
        )
    origin_host = _request_origin_host(request)
    allowlist = _allowed_emailbison_origin_hosts()
    if not origin_host:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "type": "webhook_auth_failed",
                "provider": "emailbison",
                "reason": "missing_origin",
                "message": "Missing origin host signal for EmailBison webhook",
            },
        )
    if not allowlist or not _is_allowed_origin(origin_host, allowlist):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "type": "webhook_auth_failed",
                "provider": "emailbison",
                "reason": "origin_not_allowed",
                "message": "EmailBison webhook origin is not allowlisted",
            },
        )
    return origin_host


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


def _invalid_signature_error(*, reason: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "type": "webhook_signature_invalid",
            "provider": "lob",
            "reason": reason,
            "message": message,
        },
    )


def _parse_lob_signature_timestamp(raw_timestamp: str) -> datetime | None:
    text = str(raw_timestamp).strip()
    if not text:
        return None
    if text.isdigit():
        try:
            return datetime.fromtimestamp(int(text), tz=timezone.utc)
        except (ValueError, OSError):
            return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _supported_lob_webhook_versions() -> set[str]:
    configured = str(settings.lob_webhook_schema_versions or "v1").split(",")
    versions = {item.strip() for item in configured if item.strip()}
    return versions or {"v1"}


def _extract_lob_payload_version(payload: dict[str, Any]) -> str:
    for key in ("version", "webhook_version", "schema_version"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    # Lob payloads are commonly unversioned; pin them to baseline v1 for deterministic handling.
    return "v1"


def _validate_lob_payload_schema(payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    version = _extract_lob_payload_version(payload)
    if version not in _supported_lob_webhook_versions():
        raise ValueError(f"version_unsupported:{version}")
    event_identity = payload.get("id") or payload.get("event_id")
    event_type = payload.get("type") or payload.get("event_type") or payload.get("event")
    event_ts = payload.get("date_created") or payload.get("created_at") or payload.get("time")
    body = payload.get("body") if isinstance(payload.get("body"), dict) else {}
    resource = body.get("resource") if isinstance(body.get("resource"), dict) else {}
    resource_id = (
        resource.get("id")
        or payload.get("resource_id")
        or payload.get("object_id")
        or payload.get("piece_id")
        or payload.get("mailpiece_id")
    )
    missing: list[str] = []
    if not event_identity:
        missing.append("id")
    if not event_type:
        missing.append("type")
    if not event_ts:
        missing.append("date_created")
    if not resource_id:
        missing.append("resource.id")
    if missing:
        raise ValueError(f"schema_invalid:{','.join(missing)}")
    return version, {"event_id": str(event_identity), "event_type": str(event_type), "resource_id": str(resource_id)}


def _metric_value(snapshot: dict[str, int], prefix: str) -> int:
    return sum(value for key, value in snapshot.items() if key == prefix or key.startswith(f"{prefix}|"))


def _emit_lob_slo_hooks(*, request_id: str | None, source: str) -> None:
    snapshot = metrics_snapshot()
    received = _metric_value(snapshot, "webhook.events.received")
    accepted = _metric_value(snapshot, "webhook.events.accepted")
    rejected = _metric_value(snapshot, "webhook.events.rejected")
    dead_letters = _metric_value(snapshot, "webhook.dead_letter.created")
    projection_failed = _metric_value(snapshot, "webhook.projection.failure")
    duplicate_ignored = _metric_value(snapshot, "webhook.duplicate_ignored")
    replay_processed = _metric_value(snapshot, "webhook.replay_processed")
    replay_failed = _metric_value(snapshot, "webhook.replay_failed")

    checks = [
        ("signature_reject_rate", rejected / max(1, received), settings.lob_slo_signature_reject_rate_threshold),
        ("dead_letter_rate", dead_letters / max(1, accepted), settings.lob_slo_dead_letter_rate_threshold),
        ("projection_failure_rate", projection_failed / max(1, accepted), settings.lob_slo_projection_failure_rate_threshold),
        ("replay_failure_rate", replay_failed / max(1, replay_failed + replay_processed), settings.lob_slo_replay_failure_rate_threshold),
        ("duplicate_ignore_rate", duplicate_ignored / max(1, received), settings.lob_slo_duplicate_ignore_rate_threshold),
    ]
    for metric_name, measured, threshold in checks:
        if threshold < 0:
            continue
        if measured >= threshold:
            incr_metric("webhook.slo.threshold_exceeded", provider_slug="lob", metric=metric_name)
            log_event(
                "lob_slo_threshold_exceeded",
                level=logging.WARNING,
                request_id=request_id,
                source=source,
                metric=metric_name,
                measured=round(measured, 6),
                threshold=threshold,
            )


def _verify_lob_signature(
    *,
    raw_body: bytes,
    request: Request,
    request_id: str | None,
) -> dict[str, Any]:
    raw_mode = str(settings.lob_webhook_signature_mode or "permissive_audit").strip().lower()
    mode = raw_mode if raw_mode in _LOB_SIGNATURE_MODES else "permissive_audit"
    tolerance_seconds = max(0, int(settings.lob_webhook_signature_tolerance_seconds or 0))
    secret = settings.lob_webhook_secret
    signature = request.headers.get("Lob-Signature")
    timestamp_header = request.headers.get("Lob-Signature-Timestamp")

    result = {
        "signature_mode": mode,
        "signature_verified": False,
        "signature_reason": "not_verified",
        "signature_timestamp": timestamp_header,
    }

    def _audit_failure(reason: str, message: str, level: int = logging.WARNING) -> dict[str, Any]:
        incr_metric("webhook.signature.audit_failed", provider_slug="lob", reason=reason, mode=mode)
        log_event(
            "webhook_signature_audit_failed",
            level=level,
            request_id=request_id,
            provider_slug="lob",
            reason=reason,
            mode=mode,
            message=message,
        )
        result["signature_reason"] = reason
        return result

    if mode == "enforce" and not secret:
        incr_metric("webhook.signature.enforce_config_error", provider_slug="lob")
        incr_metric("webhook.events.rejected", provider_slug="lob", reason="signature_configuration_error")
        log_event(
            "webhook_signature_enforce_config_error",
            level=logging.ERROR,
            request_id=request_id,
            provider_slug="lob",
            mode=mode,
            message="LOB_WEBHOOK_SECRET is required when mode=enforce",
        )
        _persist_lob_metrics_snapshot(source="lob_webhook_signature_reject", request_id=request_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "type": "webhook_signature_configuration_error",
                "provider": "lob",
                "message": "Webhook signature enforcement is enabled but secret is not configured",
            },
        )

    if not secret:
        return _audit_failure("secret_not_configured", "Signature secret not configured")

    if not signature:
        if mode == "enforce":
            incr_metric("webhook.signature.rejected", provider_slug="lob", reason="missing_signature")
            incr_metric("webhook.events.rejected", provider_slug="lob", reason="missing_signature")
            _persist_lob_metrics_snapshot(source="lob_webhook_signature_reject", request_id=request_id)
            raise _invalid_signature_error(
                reason="missing_signature",
                message="Missing Lob-Signature header",
            )
        return _audit_failure("missing_signature", "Missing Lob-Signature header")

    if not timestamp_header:
        if mode == "enforce":
            incr_metric("webhook.signature.rejected", provider_slug="lob", reason="missing_timestamp")
            incr_metric("webhook.events.rejected", provider_slug="lob", reason="missing_timestamp")
            _persist_lob_metrics_snapshot(source="lob_webhook_signature_reject", request_id=request_id)
            raise _invalid_signature_error(
                reason="missing_timestamp",
                message="Missing Lob-Signature-Timestamp header",
            )
        return _audit_failure("missing_timestamp", "Missing Lob-Signature-Timestamp header")

    parsed_timestamp = _parse_lob_signature_timestamp(timestamp_header)
    if parsed_timestamp is None:
        if mode == "enforce":
            incr_metric("webhook.signature.rejected", provider_slug="lob", reason="invalid_timestamp")
            incr_metric("webhook.events.rejected", provider_slug="lob", reason="invalid_timestamp")
            _persist_lob_metrics_snapshot(source="lob_webhook_signature_reject", request_id=request_id)
            raise _invalid_signature_error(
                reason="invalid_timestamp",
                message="Invalid Lob-Signature-Timestamp header format",
            )
        return _audit_failure("invalid_timestamp", "Invalid Lob-Signature-Timestamp header format")

    age_seconds = abs((datetime.now(timezone.utc) - parsed_timestamp).total_seconds())
    if tolerance_seconds > 0 and age_seconds > tolerance_seconds:
        if mode == "enforce":
            incr_metric("webhook.signature.rejected", provider_slug="lob", reason="stale_timestamp")
            incr_metric("webhook.events.rejected", provider_slug="lob", reason="stale_timestamp")
            _persist_lob_metrics_snapshot(source="lob_webhook_signature_reject", request_id=request_id)
            raise _invalid_signature_error(
                reason="stale_timestamp",
                message="Lob-Signature-Timestamp is outside accepted tolerance window",
            )
        return _audit_failure("stale_timestamp", "Lob-Signature-Timestamp outside accepted tolerance window")

    signature_input = f"{timestamp_header}.{raw_body.decode('utf-8', errors='strict')}"
    expected = hmac.new(secret.encode("utf-8"), signature_input.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        if mode == "enforce":
            incr_metric("webhook.signature.rejected", provider_slug="lob", reason="invalid_signature")
            incr_metric("webhook.events.rejected", provider_slug="lob", reason="invalid_signature")
            _persist_lob_metrics_snapshot(source="lob_webhook_signature_reject", request_id=request_id)
            raise _invalid_signature_error(
                reason="invalid_signature",
                message="Lob webhook signature verification failed",
            )
        return _audit_failure("invalid_signature", "Lob webhook signature verification failed")

    incr_metric("webhook.signature.verified", provider_slug="lob", mode=mode)
    result["signature_verified"] = True
    result["signature_reason"] = "verified"
    return result


def _lob_replay_controls() -> dict[str, float | int]:
    batch_size = max(1, min(int(settings.lob_webhook_replay_batch_size or 25), 200))
    max_events = max(1, min(int(settings.lob_webhook_replay_max_events_per_run or 500), 5000))
    sleep_ms = max(0, min(int(settings.lob_webhook_replay_sleep_ms or 0), 10000))
    max_sleep_ms = max(sleep_ms, min(int(settings.lob_webhook_replay_max_sleep_ms or 1000), 30000))
    backoff_multiplier = float(settings.lob_webhook_replay_backoff_multiplier or 2.0)
    if backoff_multiplier < 1.0:
        backoff_multiplier = 1.0
    workers = max(1, min(int(settings.lob_webhook_replay_max_concurrent_workers or 1), 32))
    queue_size = max(workers, min(int(settings.lob_webhook_replay_queue_size or workers), 500))
    return {
        "batch_size": batch_size,
        "max_events": max_events,
        "sleep_ms": sleep_ms,
        "max_sleep_ms": max_sleep_ms,
        "backoff_multiplier": backoff_multiplier,
        "workers": workers,
        "queue_size": queue_size,
    }


def _is_projection_retryable(error: Exception) -> bool:
    text = str(error).lower()
    if "timeout" in text or "temporar" in text or "connection" in text:
        return True
    if "constraint" in text or "invalid" in text or "not found" in text or "missing" in text:
        return False
    return False


def _record_dead_letter(
    *,
    provider_slug: str,
    event_key: str,
    event_type: str,
    payload: dict[str, Any],
    org_id: str | None,
    company_id: str | None,
    reason: str,
    error: str,
    retryable: bool,
    request_id: str | None,
) -> None:
    now_iso = _now_iso()
    enriched_payload = dict(payload)
    enriched_payload["_dead_letter"] = {
        "reason": reason,
        "retryable": retryable,
        "error": error,
        "recorded_at": now_iso,
    }
    try:
        updated = supabase.table("webhook_events").update(
            {
                "status": "dead_letter",
                "last_error": error,
                "payload": enriched_payload,
                "processed_at": now_iso,
            }
        ).eq("provider_slug", provider_slug).eq("event_key", event_key).execute()
        if not updated.data:
            supabase.table("webhook_events").insert(
                {
                    "provider_slug": provider_slug,
                    "event_key": event_key,
                    "event_type": event_type,
                    "status": "dead_letter",
                    "replay_count": 0,
                    "last_replay_at": None,
                    "last_error": error,
                    "org_id": org_id,
                    "company_id": company_id,
                    "payload": enriched_payload,
                    "processed_at": now_iso,
                }
            ).execute()
    except Exception as dead_letter_exc:
        log_event(
            "webhook_dead_letter_persist_failed",
            level=logging.ERROR,
            request_id=request_id,
            provider_slug=provider_slug,
            event_key=event_key,
            error=str(dead_letter_exc),
        )
        return
    incr_metric("webhook.dead_letter.recorded", provider_slug=provider_slug, reason=reason, retryable=retryable)
    incr_metric("webhook.dead_letter.created", provider_slug=provider_slug, reason=reason, retryable=retryable)
    log_event(
        "webhook_dead_letter_recorded",
        level=logging.WARNING,
        request_id=request_id,
        provider_slug=provider_slug,
        event_key=event_key,
        event_type=event_type,
        reason=reason,
        retryable=retryable,
    )


def _persist_lob_metrics_snapshot(*, source: str, request_id: str | None) -> None:
    _emit_lob_slo_hooks(request_id=request_id, source=source)
    persist_metrics_snapshot(
        supabase_client=supabase,
        source=source,
        request_id=request_id,
        reset_after_persist=False,
        export_url=settings.observability_export_url,
        export_bearer_token=settings.observability_export_bearer_token,
        export_timeout_seconds=settings.observability_export_timeout_seconds,
    )


def _dead_letter_meta(payload: dict[str, Any]) -> tuple[str | None, bool | None]:
    dead_letter = payload.get("_dead_letter") if isinstance(payload, dict) else None
    if not isinstance(dead_letter, dict):
        return None, None
    return dead_letter.get("reason"), dead_letter.get("retryable")


def _is_dead_letter_event(row: dict[str, Any]) -> bool:
    reason, _ = _dead_letter_meta(row.get("payload") or {})
    return (row.get("status") == "dead_letter") or bool(reason)


def _parse_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _persist_event_or_raise_duplicate(
    provider_slug: str,
    event_key: str,
    event_type: str,
    payload: dict[str, Any],
    org_id: str | None,
    company_id: str | None,
    initial_status: str = "processed",
) -> None:
    try:
        supabase.table("webhook_events").insert(
            {
                "provider_slug": provider_slug,
                "event_key": event_key,
                "event_type": event_type,
                "status": initial_status,
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


def _process_emailbison_event_async(
    *,
    event_key: str,
    event_type: str,
    payload: dict[str, Any],
    request_id: str | None,
) -> None:
    campaign_external_id = _extract_campaign_id(payload)
    campaign = _resolve_campaign(campaign_external_id, "emailbison") if campaign_external_id else None
    org_id = campaign["org_id"] if campaign else payload.get("org_id")
    company_id = campaign["company_id"] if campaign else payload.get("company_id")
    try:
        _apply_event_to_local_state(campaign=campaign, event_type=event_type, payload=payload)
        supabase.table("webhook_events").update(
            {
                "status": "processed",
                "processed_at": _now_iso(),
                "last_error": None,
                "org_id": org_id,
                "company_id": company_id,
            }
        ).eq("provider_slug", "emailbison").eq("event_key", event_key).execute()
        incr_metric("webhook.events.processed", provider_slug="emailbison")
        log_event(
            "webhook_processed_async",
            request_id=request_id,
            provider_slug="emailbison",
            event_type=event_type,
            event_key=event_key,
            campaign_found=bool(campaign),
        )
    except Exception as exc:
        incr_metric("webhook.events.failed", provider_slug="emailbison")
        _record_dead_letter(
            provider_slug="emailbison",
            event_key=event_key,
            event_type=event_type,
            payload=payload,
            org_id=org_id,
            company_id=company_id,
            reason="projection_failure",
            error=str(exc),
            retryable=_is_projection_retryable(exc),
            request_id=request_id,
        )
        log_event(
            "webhook_async_processing_failed",
            level=logging.ERROR,
            request_id=request_id,
            provider_slug="emailbison",
            event_type=event_type,
            event_key=event_key,
            error=str(exc),
        )


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
    piece_type = None
    if "postcard" in resource_type:
        piece_type = "postcard"
    elif "letter" in resource_type:
        piece_type = "letter"
    elif "self_mailer" in resource_type or "self mailer" in resource_type:
        piece_type = "self_mailer"
    elif "check" in resource_type:
        piece_type = "check"
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
        .select(
            "id, provider_slug, event_key, event_type, status, org_id, company_id, replay_count, last_error, payload, processed_at, created_at"
        )
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
    try:
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
                projection_row = _upsert_direct_mail_piece_from_lob_event(
                    piece_external_id=str(piece_external_id),
                    normalized_event_type=event_type,
                    payload=payload,
                    piece=piece,
                )
                if not projection_row:
                    raise ValueError("projection_unresolved")
            incr_metric("webhook.projection.success", provider_slug="lob", event_type=event_type)
        else:
            campaign_external_id = _extract_campaign_id(payload)
            campaign = _resolve_campaign(campaign_external_id, provider_slug) if campaign_external_id else None
            _apply_event_to_local_state(campaign=campaign, event_type=event_type, payload=payload)
    except Exception as exc:
        retryable = _is_projection_retryable(exc)
        now_iso = _now_iso()
        supabase.table("webhook_events").update(
            {
                "processed_at": now_iso,
                "status": "dead_letter",
                "last_error": str(exc),
            }
        ).eq("id", event_row["id"]).execute()
        incr_metric("webhook.replays.failed", provider_slug=provider_slug)
        if provider_slug == "lob":
            incr_metric("webhook.projection.failure", provider_slug="lob", event_type=event_type)
        log_event(
            "webhook_replay_failed",
            level=logging.WARNING,
            request_id=request_id,
            provider_slug=provider_slug,
            event_key=event_row.get("event_key"),
            event_type=event_type,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "type": "webhook_replay_failed",
                "provider_slug": provider_slug,
                "event_key": event_row.get("event_key"),
                "reason": str(exc),
                "retryable": retryable,
            },
        ) from exc
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
    incr_metric("webhook.replay_processed", provider_slug=provider_slug)
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


def _run_lob_replay_batch(
    *,
    rows: list[dict[str, Any]],
    request_id: str | None,
    workers: int,
    queue_size: int,
) -> list[WebhookReplayBulkItem]:
    if not rows:
        return []
    results: list[WebhookReplayBulkItem] = []

    def _work(row: dict[str, Any]) -> WebhookReplayBulkItem:
        try:
            replay_result = _replay_webhook_event("lob", row, request_id=request_id)
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, str) else json.dumps(exc.detail, sort_keys=True)
            return WebhookReplayBulkItem(
                event_key=row["event_key"],
                status="replay_failed",
                event_type=row.get("event_type"),
                error=detail,
            )
        return WebhookReplayBulkItem(
            event_key=row["event_key"],
            status="replayed",
            event_type=replay_result.event_type,
        )

    with ThreadPoolExecutor(max_workers=workers) as executor:
        pending: set[Future[WebhookReplayBulkItem]] = set()
        idx = 0
        while idx < len(rows) or pending:
            while idx < len(rows) and len(pending) < queue_size:
                pending.add(executor.submit(_work, rows[idx]))
                idx += 1
            done, pending = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                results.append(future.result())
    return results


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


@router.post("/emailbison")
async def ingest_emailbison_webhook_without_path_token():
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "type": "webhook_auth_failed",
            "provider": "emailbison",
            "reason": "missing_path_token",
            "message": "EmailBison webhook requires a secret path token",
        },
    )


@router.post("/emailbison/{path_token}")
async def ingest_emailbison_webhook(
    path_token: str,
    request: Request,
    background_tasks: BackgroundTasks,
):
    req_id = _request_id(request)
    raw_body = await request.body()
    incr_metric("webhook.events.received", provider_slug="emailbison")
    origin_host = _verify_emailbison_unsigned_contract_or_raise(request=request, path_token=path_token)

    malformed_json = False
    try:
        parsed_payload = json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError:
        parsed_payload = {"raw_body": raw_body.decode("utf-8", errors="replace")}
        malformed_json = True
    payload = parsed_payload if isinstance(parsed_payload, dict) else {"raw_payload": parsed_payload}
    event_type = _extract_event_type(payload)
    event_key = _compute_event_key(payload, raw_body)
    campaign_external_id = _extract_campaign_id(payload)
    campaign = _resolve_campaign(campaign_external_id, "emailbison") if campaign_external_id else None
    org_id = campaign["org_id"] if campaign else None
    company_id = campaign["company_id"] if campaign else None
    received_at = _now_iso()

    enriched_payload = dict(payload)
    enriched_payload["_ingestion"] = {
        "provider_slug": "emailbison",
        "trust_mode": "unsigned_origin_plus_path_token",
        "origin_host": origin_host,
        "received_at": received_at,
        "request_headers": {k: v for k, v in request.headers.items()},
        "raw_body": raw_body.decode("utf-8", errors="replace"),
        "request_id": req_id,
    }
    if malformed_json:
        enriched_payload["malformed_json"] = True

    log_event(
        "webhook_received",
        request_id=req_id,
        provider_slug="emailbison",
        event_type=event_type,
        event_key=event_key,
        trust_mode="unsigned_origin_plus_path_token",
        origin_host=origin_host,
        has_campaign_id=bool(campaign_external_id),
    )

    try:
        _persist_event_or_raise_duplicate(
            "emailbison",
            event_key,
            event_type,
            enriched_payload,
            org_id,
            company_id,
            initial_status="accepted",
        )
    except HTTPException as exc:
        if exc.status_code == status.HTTP_200_OK:
            incr_metric("webhook.events.duplicate", provider_slug="emailbison")
            incr_metric("webhook.duplicate_ignored", provider_slug="emailbison")
            return {"status": "duplicate_ignored", "event_type": event_type, "event_key": event_key}
        raise

    incr_metric("webhook.events.accepted", provider_slug="emailbison")
    background_tasks.add_task(
        _process_emailbison_event_async,
        event_key=event_key,
        event_type=event_type,
        payload=enriched_payload,
        request_id=req_id,
    )
    return {
        "status": "accepted",
        "event_type": event_type,
        "event_key": event_key,
        "trust_mode": "unsigned_origin_plus_path_token",
        "non_cryptographic_trust": True,
    }


@router.post("/lob")
async def ingest_lob_webhook(request: Request):
    req_id = _request_id(request)
    raw_body = await request.body()
    signature_result = _verify_lob_signature(raw_body=raw_body, request=request, request_id=req_id)
    signature_mode = signature_result["signature_mode"]
    incr_metric("webhook.events.received", provider_slug="lob")
    incr_metric("webhook.events.accepted", provider_slug="lob", signature_mode=signature_mode)

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError:
        payload = {"raw_body": raw_body.decode("utf-8", errors="replace"), "malformed_json": True}

    validation_error: str | None = None
    schema_details: dict[str, Any] | None = None
    payload_version = _extract_lob_payload_version(payload) if isinstance(payload, dict) else "v1"
    if not payload.get("malformed_json"):
        try:
            payload_version, schema_details = _validate_lob_payload_schema(payload)
        except ValueError as exc:
            validation_error = str(exc)

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
        "payload_version": payload_version,
        "signature_mode": signature_mode,
        "signature_verified": signature_result.get("signature_verified", False),
        "signature_reason": signature_result.get("signature_reason"),
        "signature_timestamp": signature_result.get("signature_timestamp"),
        "request_headers": {k: v for k, v in request.headers.items()},
        "request_id": req_id,
    }
    if schema_details:
        enriched_payload["_ingestion"]["schema_details"] = schema_details
    if validation_error:
        err_kind, _, err_detail = validation_error.partition(":")
        enriched_payload["_schema_validation"] = {
            "status": "failed",
            "reason": err_kind or "schema_invalid",
            "detail": err_detail,
        }
    else:
        enriched_payload["_schema_validation"] = {"status": "ok", "version": payload_version}
    if piece_external_id:
        enriched_payload["resource_id"] = str(piece_external_id)

    log_event(
        "webhook_received",
        request_id=req_id,
        provider_slug="lob",
        event_type=normalized_event_type,
        event_key=event_key,
        signature_mode=signature_mode,
        signature_verified=signature_result.get("signature_verified", False),
        signature_reason=signature_result.get("signature_reason"),
        has_piece_id=bool(piece_external_id),
    )

    try:
        if payload.get("malformed_json"):
            raise ValueError("malformed_json_payload")
        if validation_error:
            raise ValueError(validation_error)
        _persist_event_or_raise_duplicate("lob", event_key, normalized_event_type, enriched_payload, org_id, company_id)
        if piece_external_id:
            projection_row = _upsert_direct_mail_piece_from_lob_event(
                piece_external_id=str(piece_external_id),
                normalized_event_type=normalized_event_type,
                payload=enriched_payload,
                piece=piece,
            )
            if not projection_row:
                raise ValueError("projection_unresolved")
            incr_metric("webhook.projection.success", provider_slug="lob", event_type=normalized_event_type)
        else:
            incr_metric("webhook.projection.success", provider_slug="lob", event_type=normalized_event_type)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_200_OK:
            incr_metric("webhook.events.duplicate", provider_slug="lob")
            incr_metric("webhook.duplicate_ignored", provider_slug="lob")
            log_event(
                "webhook_duplicate_ignored",
                request_id=req_id,
                provider_slug="lob",
                event_type=normalized_event_type,
                event_key=event_key,
            )
            _persist_lob_metrics_snapshot(source="lob_webhook_ingest", request_id=req_id)
            return {
                "status": "duplicate_ignored",
                "event_type": normalized_event_type,
                "event_key": event_key,
                "signature_mode": signature_mode,
                "signature_verified": signature_result.get("signature_verified", False),
                "signature_reason": signature_result.get("signature_reason"),
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
        incr_metric("webhook.projection.failure", provider_slug="lob", event_type=normalized_event_type)
        log_event(
            "webhook_failed",
            level=logging.ERROR,
            request_id=req_id,
            provider_slug="lob",
            event_type=normalized_event_type,
            event_key=event_key,
            error=str(exc),
        )
        retryable = _is_projection_retryable(exc)
        reason = "projection_failure"
        if "malformed_json_payload" in str(exc):
            reason = "malformed_payload"
        elif "schema_invalid:" in str(exc):
            reason = "schema_invalid"
        elif "version_unsupported:" in str(exc):
            reason = "version_unsupported"
        elif "projection_unresolved" in str(exc):
            reason = "projection_unresolved"
        _record_dead_letter(
            provider_slug="lob",
            event_key=event_key,
            event_type=normalized_event_type,
            payload=enriched_payload,
            org_id=org_id,
            company_id=company_id,
            reason=reason,
            error=str(exc),
            retryable=retryable,
            request_id=req_id,
        )
        _persist_lob_metrics_snapshot(source="lob_webhook_ingest", request_id=req_id)
        return {
            "status": "dead_letter_recorded",
            "event_type": normalized_event_type,
            "event_key": event_key,
            "signature_mode": signature_mode,
            "signature_verified": signature_result.get("signature_verified", False),
            "signature_reason": signature_result.get("signature_reason"),
            "dead_letter": {"reason": reason, "retryable": retryable},
        }

    incr_metric("webhook.events.processed", provider_slug="lob")
    log_event(
        "webhook_processed",
        request_id=req_id,
        provider_slug="lob",
        event_type=normalized_event_type,
        event_key=event_key,
        signature_mode=signature_mode,
        signature_verified=signature_result.get("signature_verified", False),
        signature_reason=signature_result.get("signature_reason"),
        piece_found=bool(piece),
    )
    _persist_lob_metrics_snapshot(source="lob_webhook_ingest", request_id=req_id)
    return {
        "status": "processed",
        "event_type": normalized_event_type,
        "event_key": event_key,
        "signature_mode": signature_mode,
        "signature_verified": signature_result.get("signature_verified", False),
        "signature_reason": signature_result.get("signature_reason"),
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
    if provider_slug and provider_slug not in {"smartlead", "heyreach", "emailbison", "lob"}:
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


@router.get("/dead-letters", response_model=list[WebhookDeadLetterListItem])
async def list_lob_dead_letters(
    from_ts: datetime | None = None,
    to_ts: datetime | None = None,
    reason: str | None = None,
    replay_status: str = "all",
    org_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
    _ctx: SuperAdminContext = Depends(get_current_super_admin),
):
    if from_ts and to_ts and from_ts > to_ts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"type": "invalid_filter", "message": "from_ts must be before or equal to to_ts"},
        )
    max_window_days = 93
    if from_ts and to_ts and (to_ts - from_ts).days > max_window_days:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"type": "invalid_filter", "message": f"date range exceeds {max_window_days} days"},
        )
    if replay_status not in {"all", "pending", "replayed"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"type": "invalid_filter", "message": "replay_status must be one of: all, pending, replayed"},
        )
    bounded_limit = max(1, min(limit, 200))
    bounded_offset = max(0, offset)
    query = supabase.table("webhook_events").select(
        "id, provider_slug, event_key, event_type, status, org_id, company_id, replay_count, last_error, payload, created_at, processed_at"
    ).eq("provider_slug", "lob")
    if replay_status == "pending":
        query = query.eq("status", "dead_letter")
    elif replay_status == "replayed":
        query = query.eq("status", "replayed")
    if org_id:
        query = query.eq("org_id", org_id)
    rows = query.execute().data or []
    filtered: list[dict[str, Any]] = []
    for row in rows:
        payload = row.get("payload") or {}
        dl_reason, dl_retryable = _dead_letter_meta(payload)
        if not _is_dead_letter_event(row):
            continue
        created_at = _parse_ts(row.get("created_at"))
        if from_ts and created_at and created_at < from_ts:
            continue
        if to_ts and created_at and created_at > to_ts:
            continue
        if reason and dl_reason != reason:
            continue
        if replay_status == "pending" and row.get("status") != "dead_letter":
            continue
        if replay_status == "replayed" and row.get("status") != "replayed":
            continue
        filtered.append(
            {
                "provider_slug": "lob",
                "event_key": row.get("event_key"),
                "event_type": row.get("event_type"),
                "status": row.get("status"),
                "org_id": row.get("org_id"),
                "company_id": row.get("company_id"),
                "dead_letter_reason": dl_reason,
                "dead_letter_retryable": dl_retryable,
                "last_error": row.get("last_error"),
                "replay_count": row.get("replay_count"),
                "created_at": row.get("created_at"),
                "processed_at": row.get("processed_at"),
            }
        )
    filtered = sorted(filtered, key=lambda row: row.get("created_at") or "", reverse=True)
    return filtered[bounded_offset:bounded_offset + bounded_limit]


@router.get("/dead-letters/{event_key}", response_model=WebhookDeadLetterDetailResponse)
async def get_lob_dead_letter_detail(
    event_key: str,
    _ctx: SuperAdminContext = Depends(get_current_super_admin),
):
    row = _get_webhook_event("lob", event_key)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dead-letter event not found")
    if not _is_dead_letter_event(row):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dead-letter event not found")
    payload = row.get("payload") or {}
    dl_reason, dl_retryable = _dead_letter_meta(payload)
    return WebhookDeadLetterDetailResponse(
        provider_slug="lob",
        event_key=row.get("event_key"),
        event_type=row.get("event_type"),
        status=row.get("status"),
        org_id=row.get("org_id"),
        company_id=row.get("company_id"),
        dead_letter_reason=dl_reason,
        dead_letter_retryable=dl_retryable,
        replay_count=row.get("replay_count"),
        last_error=row.get("last_error"),
        payload=payload,
        created_at=_parse_ts(row.get("created_at")),
        processed_at=_parse_ts(row.get("processed_at")),
    )


@router.post("/dead-letters/replay", response_model=WebhookDeadLetterReplayResponse)
async def replay_lob_dead_letters(
    data: WebhookDeadLetterReplayRequest,
    request: Request,
    _ctx: SuperAdminContext = Depends(get_current_super_admin),
):
    if not data.event_keys:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="event_keys cannot be empty")
    controls = _lob_replay_controls()
    if len(data.event_keys) > int(controls["max_events"]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Requested replay count exceeds max events per run ({int(controls['max_events'])})",
        )
    req_id = _request_id(request)
    replayed = 0
    not_found = 0
    failed = 0
    results: list[WebhookReplayBulkItem] = []
    seen_event_keys: set[str] = set()
    batch_size = int(controls["batch_size"])
    sleep_seconds = float(int(controls["sleep_ms"]) / 1000.0)
    max_sleep_seconds = float(int(controls["max_sleep_ms"]) / 1000.0)
    backoff = float(controls["backoff_multiplier"])
    workers = int(controls["workers"])
    queue_size = int(controls["queue_size"])
    current_sleep = sleep_seconds
    for start in range(0, len(data.event_keys), batch_size):
        batch = data.event_keys[start:start + batch_size]
        replay_rows: list[dict[str, Any]] = []
        for event_key in batch:
            if event_key in seen_event_keys:
                results.append(
                    WebhookReplayBulkItem(
                        event_key=event_key,
                        status="replayed",
                        event_type=None,
                        error="duplicate_request_key_ignored",
                    )
                )
                continue
            seen_event_keys.add(event_key)
            row = _get_webhook_event("lob", event_key)
            if not row or not _is_dead_letter_event(row):
                not_found += 1
                results.append(WebhookReplayBulkItem(event_key=event_key, status="not_found", event_type=None))
                continue
            replay_rows.append(row)
        batch_results = _run_lob_replay_batch(
            rows=replay_rows,
            request_id=req_id,
            workers=workers,
            queue_size=queue_size,
        )
        batch_failed = 0
        transient_failed = 0
        for item in batch_results:
            results.append(item)
            if item.status == "replayed":
                replayed += 1
                incr_metric("webhook.dead_letter.replayed", provider_slug="lob")
                continue
            failed += 1
            batch_failed += 1
            if item.error and '"retryable": true' in item.error.lower():
                transient_failed += 1
            incr_metric("webhook.replay_failed", provider_slug="lob")
        if start + batch_size < len(data.event_keys) and current_sleep > 0:
            time.sleep(current_sleep)
            if transient_failed > 0:
                current_sleep = min(max_sleep_seconds, current_sleep * backoff)
            elif batch_failed > 0:
                current_sleep = min(max_sleep_seconds, current_sleep * backoff)
            else:
                current_sleep = max(sleep_seconds, current_sleep / max(1.0, backoff))
    log_event(
        "dead_letter_replay_completed",
        request_id=req_id,
        provider_slug="lob",
        requested=len(data.event_keys),
        replayed=replayed,
        not_found=not_found,
        failed=failed,
    )
    _persist_lob_metrics_snapshot(source="lob_dead_letter_replay", request_id=req_id)
    return WebhookDeadLetterReplayResponse(
        requested=len(data.event_keys),
        replayed=replayed,
        not_found=not_found,
        failed=failed,
        results=results,
    )


@router.post("/replay/{provider_slug}/{event_key}", response_model=WebhookReplayResponse)
async def replay_webhook_event(
    provider_slug: str,
    event_key: str,
    request: Request,
    _ctx: SuperAdminContext = Depends(get_current_super_admin),
):
    if provider_slug not in {"smartlead", "heyreach", "emailbison", "lob"}:
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
    controls = _lob_replay_controls() if data.provider_slug == "lob" else None
    if controls and len(data.event_keys) > int(controls["max_events"]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Requested replay count exceeds max events per run ({int(controls['max_events'])})",
        )
    replayed = 0
    not_found = 0
    replay_failed = 0
    results: list[WebhookReplayBulkItem] = []
    seen_event_keys: set[str] = set()
    if controls:
        batch_size = int(controls["batch_size"])
        sleep_seconds = float(int(controls["sleep_ms"]) / 1000.0)
        max_sleep_seconds = float(int(controls["max_sleep_ms"]) / 1000.0)
        backoff = float(controls["backoff_multiplier"])
        workers = int(controls["workers"])
        queue_size = int(controls["queue_size"])
        current_sleep = sleep_seconds
        for start in range(0, len(data.event_keys), batch_size):
            batch = data.event_keys[start:start + batch_size]
            replay_rows: list[dict[str, Any]] = []
            for event_key in batch:
                if event_key in seen_event_keys:
                    results.append(
                        WebhookReplayBulkItem(
                            event_key=event_key,
                            status="replayed",
                            event_type=None,
                            error="duplicate_request_key_ignored",
                        )
                    )
                    continue
                seen_event_keys.add(event_key)
                event_row = _get_webhook_event(data.provider_slug, event_key)
                if not event_row:
                    not_found += 1
                    results.append(WebhookReplayBulkItem(event_key=event_key, status="not_found", event_type=None))
                    continue
                replay_rows.append(event_row)
            batch_results = _run_lob_replay_batch(
                rows=replay_rows,
                request_id=req_id,
                workers=workers,
                queue_size=queue_size,
            )
            batch_failed = 0
            transient_failed = 0
            for item in batch_results:
                results.append(item)
                if item.status == "replayed":
                    replayed += 1
                    continue
                replay_failed += 1
                batch_failed += 1
                if item.error and '"retryable": true' in item.error.lower():
                    transient_failed += 1
                incr_metric("webhook.replay_failed", provider_slug=data.provider_slug)
            if start + batch_size < len(data.event_keys) and current_sleep > 0:
                time.sleep(current_sleep)
                if transient_failed > 0:
                    current_sleep = min(max_sleep_seconds, current_sleep * backoff)
                elif batch_failed > 0:
                    current_sleep = min(max_sleep_seconds, current_sleep * backoff)
                else:
                    current_sleep = max(sleep_seconds, current_sleep / max(1.0, backoff))
    else:
        for event_key in data.event_keys:
            if event_key in seen_event_keys:
                results.append(
                    WebhookReplayBulkItem(
                        event_key=event_key,
                        status="replayed",
                        event_type=None,
                        error="duplicate_request_key_ignored",
                    )
                )
                continue
            seen_event_keys.add(event_key)
            event_row = _get_webhook_event(data.provider_slug, event_key)
            if not event_row:
                not_found += 1
                results.append(WebhookReplayBulkItem(event_key=event_key, status="not_found", event_type=None))
                continue
            try:
                replay_result = _replay_webhook_event(data.provider_slug, event_row, request_id=req_id)
            except HTTPException as exc:
                replay_failed += 1
                incr_metric("webhook.replay_failed", provider_slug=data.provider_slug)
                results.append(
                    WebhookReplayBulkItem(
                        event_key=event_key,
                        status="replay_failed",
                        event_type=event_row.get("event_type"),
                        error=str(exc.detail),
                    )
                )
                continue
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
        replay_failed=replay_failed,
    )
    if data.provider_slug == "lob":
        _persist_lob_metrics_snapshot(source="webhook_replay_bulk", request_id=req_id)
    else:
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
    controls = _lob_replay_controls() if data.provider_slug == "lob" else None
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
    if controls and len(selected) > int(controls["max_events"]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Matched replay count exceeds max events per run ({int(controls['max_events'])})",
        )

    replayed = 0
    replay_failed = 0
    results: list[WebhookReplayBulkItem] = []
    if controls:
        batch_size = int(controls["batch_size"])
        sleep_seconds = float(int(controls["sleep_ms"]) / 1000.0)
        max_sleep_seconds = float(int(controls["max_sleep_ms"]) / 1000.0)
        backoff = float(controls["backoff_multiplier"])
        workers = int(controls["workers"])
        queue_size = int(controls["queue_size"])
        current_sleep = sleep_seconds
        for start in range(0, len(selected), batch_size):
            batch = selected[start:start + batch_size]
            batch_results = _run_lob_replay_batch(
                rows=batch,
                request_id=req_id,
                workers=workers,
                queue_size=queue_size,
            )
            batch_failed = 0
            transient_failed = 0
            for item in batch_results:
                results.append(item)
                if item.status == "replayed":
                    replayed += 1
                    continue
                replay_failed += 1
                batch_failed += 1
                if item.error and '"retryable": true' in item.error.lower():
                    transient_failed += 1
                incr_metric("webhook.replay_failed", provider_slug=data.provider_slug)
            if start + batch_size < len(selected) and current_sleep > 0:
                time.sleep(current_sleep)
                if transient_failed > 0:
                    current_sleep = min(max_sleep_seconds, current_sleep * backoff)
                elif batch_failed > 0:
                    current_sleep = min(max_sleep_seconds, current_sleep * backoff)
                else:
                    current_sleep = max(sleep_seconds, current_sleep / max(1.0, backoff))
    else:
        for row in selected:
            try:
                replay_result = _replay_webhook_event(data.provider_slug, row, request_id=req_id)
            except HTTPException as exc:
                replay_failed += 1
                incr_metric("webhook.replay_failed", provider_slug=data.provider_slug)
                results.append(
                    WebhookReplayBulkItem(
                        event_key=row["event_key"],
                        status="replay_failed",
                        event_type=row.get("event_type"),
                        error=str(exc.detail),
                    )
                )
                continue
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
        replay_failed=replay_failed,
        limit=data.limit,
    )
    if data.provider_slug == "lob":
        _persist_lob_metrics_snapshot(source="webhook_replay_query", request_id=req_id)
    else:
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
