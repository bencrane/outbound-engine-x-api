from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from src.auth import AuthContext, get_current_auth
from src.config import settings
from src.db import supabase
from src.domain.provider_errors import provider_error_detail, provider_error_http_status
from src.models.direct_mail import (
    DirectMailAddressVerificationResponse,
    DirectMailAddressVerificationUSRequest,
    DirectMailAddressVerificationUSBulkRequest,
    DirectMailPieceCancelResponse,
    DirectMailPieceCreateRequest,
    DirectMailPieceListResponse,
    DirectMailPieceResponse,
)
from src.providers.lob.client import (
    LobProviderError,
    cancel_check as lob_cancel_check,
    cancel_letter as lob_cancel_letter,
    cancel_postcard as lob_cancel_postcard,
    cancel_self_mailer as lob_cancel_self_mailer,
    create_check as lob_create_check,
    create_letter as lob_create_letter,
    create_postcard as lob_create_postcard,
    create_self_mailer as lob_create_self_mailer,
    get_check as lob_get_check,
    get_letter as lob_get_letter,
    get_postcard as lob_get_postcard,
    get_self_mailer as lob_get_self_mailer,
    list_checks as lob_list_checks,
    list_letters as lob_list_letters,
    list_postcards as lob_list_postcards,
    list_self_mailers as lob_list_self_mailers,
    verify_address_us_bulk as lob_verify_address_us_bulk,
    verify_address_us_single as lob_verify_address_us_single,
)
from src.observability import incr_metric, log_event


router = APIRouter(prefix="/api/direct-mail", tags=["direct-mail"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def _request_id(request: Request | None) -> str | None:
    if not request:
        return None
    return getattr(getattr(request, "state", None), "request_id", None)


def _raise_provider_http_error(operation: str, exc: LobProviderError, request_id: str | None = None) -> None:
    incr_metric(
        "direct_mail.requests.failed",
        operation=operation,
        provider="lob",
        category=exc.category,
        retryable=exc.retryable,
    )
    log_event(
        "direct_mail_operation_failed",
        level=logging.WARNING,
        request_id=request_id,
        operation=operation,
        provider="lob",
        category=exc.category,
        retryable=exc.retryable,
        error=str(exc),
    )
    raise HTTPException(
        status_code=provider_error_http_status(exc),
        detail=provider_error_detail(provider="lob", operation=operation, exc=exc),
    ) from exc


def _provider_not_implemented_for_capability(provider_slug: str, *, operation: str, request_id: str | None) -> HTTPException:
    incr_metric("direct_mail.requests.failed", operation=operation, provider=provider_slug, category="not_implemented")
    log_event(
        "direct_mail_provider_not_implemented",
        level=logging.WARNING,
        request_id=request_id,
        operation=operation,
        provider=provider_slug,
    )
    return HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail={
            "type": "provider_not_implemented",
            "capability": "direct_mail",
            "provider": provider_slug,
            "message": f"direct_mail workflows are not implemented for provider: {provider_slug}",
        },
    )


def _ensure_lob_provider(provider_slug: str, *, operation: str, request_id: str | None) -> None:
    if provider_slug != "lob":
        raise _provider_not_implemented_for_capability(provider_slug, operation=operation, request_id=request_id)


def _resolve_company_id(auth: AuthContext, company_id: str | None) -> str:
    if auth.company_id:
        if company_id and company_id != auth.company_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")
        return auth.company_id

    if auth.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    if not company_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="company_id is required for org-level callers",
        )
    return company_id


def _get_company(auth: AuthContext, company_id: str) -> dict[str, Any]:
    result = supabase.table("companies").select("id, org_id").eq(
        "id", company_id
    ).eq("org_id", auth.org_id).is_("deleted_at", "null").execute()
    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")
    return result.data[0]


def _get_provider_by_id(provider_id: str) -> dict[str, Any]:
    result = supabase.table("providers").select("id, slug, capability_id").eq("id", provider_id).execute()
    if not result.data:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Provider not configured")
    return result.data[0]


def _get_direct_mail_entitlement(org_id: str, company_id: str) -> dict[str, Any]:
    capability = supabase.table("capabilities").select("id").eq("slug", "direct_mail").execute()
    if not capability.data:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Capability not configured")
    capability_id = capability.data[0]["id"]

    entitlement = supabase.table("company_entitlements").select("*").eq(
        "org_id", org_id
    ).eq("company_id", company_id).eq("capability_id", capability_id).is_("deleted_at", "null").execute()
    if not entitlement.data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Direct mail entitlement not found for company",
        )
    return entitlement.data[0]


def _get_org_provider_config(org_id: str, provider_slug: str) -> dict[str, Any]:
    result = supabase.table("organizations").select("provider_configs").eq(
        "id", org_id
    ).is_("deleted_at", "null").execute()
    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    provider_configs = result.data[0].get("provider_configs") or {}
    provider_config = provider_configs.get(provider_slug) or {}
    api_key = provider_config.get("api_key") or settings.lob_api_key_test
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Missing org-level {provider_slug} API key",
        )
    return {"api_key": api_key, "instance_url": provider_config.get("instance_url")}


def _normalize_piece_status(value: str | None) -> str:
    if not value:
        return "unknown"
    key = str(value).strip().lower()
    mapping = {
        "queued": "queued",
        "pending": "queued",
        "created": "queued",
        "processing": "processing",
        "rendered": "processing",
        "in_production": "processing",
        "processed": "ready_for_mail",
        "ready_for_mail": "ready_for_mail",
        "in_transit": "in_transit",
        "mailed": "in_transit",
        "delivered": "delivered",
        "returned": "returned",
        "cancelled": "canceled",
        "canceled": "canceled",
        "deleted": "canceled",
        "failed": "failed",
    }
    return mapping.get(key, "unknown")


def _normalize_verify_status(payload: dict[str, Any]) -> str:
    deliverability = str(payload.get("deliverability") or "").lower()
    if deliverability in {"deliverable", "deliverable_missing_unit", "deliverable_incorrect_unit"}:
        return "deliverable"
    if deliverability in {"undeliverable", "no_match"}:
        return "undeliverable"

    dpv_code = str(payload.get("dpv_code") or "").upper()
    if dpv_code in {"Y", "S"}:
        return "deliverable"
    if dpv_code in {"D"}:
        return "corrected"
    if dpv_code in {"N"}:
        return "undeliverable"
    if dpv_code in {"A"}:
        return "partial"
    return "unknown"


def _extract_normalized_address(payload: dict[str, Any]) -> dict[str, Any] | None:
    normalized = {
        "primary_line": payload.get("primary_line") or payload.get("address_line1"),
        "secondary_line": payload.get("secondary_line") or payload.get("address_line2"),
        "city": payload.get("city"),
        "state": payload.get("state"),
        "zip_code": payload.get("zip_code") or payload.get("zip"),
        "country": payload.get("country") or "US",
    }
    if any(value is not None for value in normalized.values()):
        return normalized
    return None


def _extract_piece_list_payload(provider_payload: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(provider_payload.get("data"), list):
        return provider_payload["data"]
    if isinstance(provider_payload.get("items"), list):
        return provider_payload["items"]
    return []


def _upsert_piece(
    *,
    org_id: str,
    company_id: str,
    provider_id: str,
    piece_type: str,
    provider_piece: dict[str, Any],
) -> None:
    external_piece_id = provider_piece.get("id")
    if not external_piece_id:
        return

    existing = supabase.table("company_direct_mail_pieces").select("id").eq(
        "org_id", org_id
    ).eq("provider_id", provider_id).eq("external_piece_id", str(external_piece_id)).is_("deleted_at", "null").execute()

    status_value = _normalize_piece_status(provider_piece.get("status"))
    payload = {
        "org_id": org_id,
        "company_id": company_id,
        "provider_id": provider_id,
        "external_piece_id": str(external_piece_id),
        "piece_type": piece_type,
        "status": status_value,
        "send_date": provider_piece.get("send_date"),
        "metadata": provider_piece.get("metadata"),
        "raw_payload": provider_piece,
        "updated_at": _now_iso(),
    }
    if existing.data:
        supabase.table("company_direct_mail_pieces").update(payload).eq(
            "id", existing.data[0]["id"]
        ).eq("org_id", org_id).execute()
    else:
        payload["created_by_user_id"] = None
        payload["created_at"] = _now_iso()
        supabase.table("company_direct_mail_pieces").insert(payload).execute()


def _get_piece_for_auth(auth: AuthContext, *, piece_id: str, piece_type: str) -> dict[str, Any]:
    query = supabase.table("company_direct_mail_pieces").select("*").eq(
        "org_id", auth.org_id
    ).eq("external_piece_id", piece_id).eq("piece_type", piece_type).is_("deleted_at", "null")
    if auth.company_id:
        query = query.eq("company_id", auth.company_id)
    result = query.execute()
    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Direct mail piece not found")
    return result.data[0]


def _piece_row_to_response(row: dict[str, Any]) -> DirectMailPieceResponse:
    created_at = _parse_datetime(row.get("created_at")) or datetime.now(timezone.utc)
    updated_at = _parse_datetime(row.get("updated_at")) or created_at
    send_date = _parse_datetime(row.get("send_date"))
    return DirectMailPieceResponse(
        id=row["external_piece_id"],
        type=row["piece_type"],
        status=row.get("status") or "unknown",
        created_at=created_at,
        updated_at=updated_at,
        send_date=send_date,
        metadata=row.get("metadata"),
        provider=None,
    )


@router.post("/verify-address/us", response_model=DirectMailAddressVerificationResponse)
async def verify_address_us(
    data: DirectMailAddressVerificationUSRequest,
    request: Request,
    company_id: str | None = Query(None),
    auth: AuthContext = Depends(get_current_auth),
):
    request_id = _request_id(request)
    incr_metric("direct_mail.requests.received", operation="verify_address_us", provider="lob")
    resolved_company_id = _resolve_company_id(auth, company_id)
    _get_company(auth, resolved_company_id)
    entitlement = _get_direct_mail_entitlement(auth.org_id, resolved_company_id)
    provider = _get_provider_by_id(entitlement["provider_id"])
    _ensure_lob_provider(provider["slug"], operation="verify_address_us", request_id=request_id)
    creds = _get_org_provider_config(auth.org_id, "lob")

    try:
        provider_payload = lob_verify_address_us_single(
            api_key=creds["api_key"],
            base_url=creds.get("instance_url"),
            payload=data.payload,
        )
    except LobProviderError as exc:
        _raise_provider_http_error("verify_address_us", exc, request_id=request_id)

    normalized = _normalize_verify_status(provider_payload)
    incr_metric("direct_mail.requests.processed", operation="verify_address_us", provider="lob")
    log_event(
        "direct_mail_operation_processed",
        request_id=request_id,
        operation="verify_address_us",
        provider="lob",
        company_id=resolved_company_id,
        normalized_status=normalized,
    )
    return DirectMailAddressVerificationResponse(
        status=normalized,
        deliverability=normalized,
        normalized_address=_extract_normalized_address(provider_payload),
        raw_provider_status=provider_payload.get("deliverability"),
    )


@router.post("/verify-address/us/bulk", response_model=list[DirectMailAddressVerificationResponse])
async def verify_address_us_bulk(
    data: DirectMailAddressVerificationUSBulkRequest,
    request: Request,
    company_id: str | None = Query(None),
    auth: AuthContext = Depends(get_current_auth),
):
    request_id = _request_id(request)
    incr_metric("direct_mail.requests.received", operation="verify_address_us_bulk", provider="lob")
    resolved_company_id = _resolve_company_id(auth, company_id)
    _get_company(auth, resolved_company_id)
    entitlement = _get_direct_mail_entitlement(auth.org_id, resolved_company_id)
    provider = _get_provider_by_id(entitlement["provider_id"])
    _ensure_lob_provider(provider["slug"], operation="verify_address_us_bulk", request_id=request_id)
    creds = _get_org_provider_config(auth.org_id, "lob")

    try:
        provider_payload = lob_verify_address_us_bulk(
            api_key=creds["api_key"],
            base_url=creds.get("instance_url"),
            payload=data.payload,
        )
    except LobProviderError as exc:
        _raise_provider_http_error("verify_address_us_bulk", exc, request_id=request_id)

    rows = _extract_piece_list_payload(provider_payload)
    if not rows and isinstance(provider_payload.get("addresses"), list):
        rows = provider_payload["addresses"]
    if not rows and isinstance(provider_payload, dict):
        rows = [provider_payload]

    normalized_rows = [
        DirectMailAddressVerificationResponse(
            status=_normalize_verify_status(row),
            deliverability=_normalize_verify_status(row),
            normalized_address=_extract_normalized_address(row),
            raw_provider_status=row.get("deliverability"),
        )
        for row in rows
    ]
    incr_metric("direct_mail.requests.processed", operation="verify_address_us_bulk", provider="lob")
    log_event(
        "direct_mail_operation_processed",
        request_id=request_id,
        operation="verify_address_us_bulk",
        provider="lob",
        company_id=resolved_company_id,
        result_count=len(normalized_rows),
    )
    return normalized_rows


@router.post("/postcards", response_model=DirectMailPieceResponse, status_code=status.HTTP_201_CREATED)
async def create_postcard(
    data: DirectMailPieceCreateRequest,
    request: Request,
    auth: AuthContext = Depends(get_current_auth),
):
    request_id = _request_id(request)
    incr_metric("direct_mail.requests.received", operation="create_postcard", provider="lob")
    resolved_company_id = _resolve_company_id(auth, data.company_id)
    _get_company(auth, resolved_company_id)
    entitlement = _get_direct_mail_entitlement(auth.org_id, resolved_company_id)
    provider = _get_provider_by_id(entitlement["provider_id"])
    _ensure_lob_provider(provider["slug"], operation="create_postcard", request_id=request_id)
    creds = _get_org_provider_config(auth.org_id, "lob")

    try:
        provider_piece = lob_create_postcard(
            api_key=creds["api_key"],
            base_url=creds.get("instance_url"),
            payload=data.payload,
            idempotency_key=data.idempotency_key,
            idempotency_in_query=(data.idempotency_location == "query"),
        )
    except LobProviderError as exc:
        _raise_provider_http_error("create_postcard", exc, request_id=request_id)

    if not provider_piece.get("id"):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Postcard create failed: provider did not return piece id",
        )

    _upsert_piece(
        org_id=auth.org_id,
        company_id=resolved_company_id,
        provider_id=provider["id"],
        piece_type="postcard",
        provider_piece=provider_piece,
    )
    row = _get_piece_for_auth(auth, piece_id=str(provider_piece["id"]), piece_type="postcard")
    incr_metric("direct_mail.requests.processed", operation="create_postcard", provider="lob")
    log_event(
        "direct_mail_operation_processed",
        request_id=request_id,
        operation="create_postcard",
        provider="lob",
        company_id=resolved_company_id,
        piece_id=str(provider_piece["id"]),
        status=row.get("status"),
    )
    return _piece_row_to_response(row)


@router.get("/postcards", response_model=DirectMailPieceListResponse)
async def list_postcards(
    request: Request,
    company_id: str | None = Query(None),
    auth: AuthContext = Depends(get_current_auth),
):
    request_id = _request_id(request)
    incr_metric("direct_mail.requests.received", operation="list_postcards", provider="lob")
    resolved_company_id = _resolve_company_id(auth, company_id)
    _get_company(auth, resolved_company_id)
    entitlement = _get_direct_mail_entitlement(auth.org_id, resolved_company_id)
    provider = _get_provider_by_id(entitlement["provider_id"])
    _ensure_lob_provider(provider["slug"], operation="list_postcards", request_id=request_id)
    creds = _get_org_provider_config(auth.org_id, "lob")

    try:
        provider_payload = lob_list_postcards(
            api_key=creds["api_key"],
            base_url=creds.get("instance_url"),
            params={"limit": 100},
        )
    except LobProviderError as exc:
        _raise_provider_http_error("list_postcards", exc, request_id=request_id)

    for piece in _extract_piece_list_payload(provider_payload):
        _upsert_piece(
            org_id=auth.org_id,
            company_id=resolved_company_id,
            provider_id=provider["id"],
            piece_type="postcard",
            provider_piece=piece,
        )

    rows = supabase.table("company_direct_mail_pieces").select("*").eq(
        "org_id", auth.org_id
    ).eq("company_id", resolved_company_id).eq("piece_type", "postcard").is_("deleted_at", "null").execute().data or []
    pieces = [_piece_row_to_response(row) for row in rows]
    incr_metric("direct_mail.requests.processed", operation="list_postcards", provider="lob")
    log_event(
        "direct_mail_operation_processed",
        request_id=request_id,
        operation="list_postcards",
        provider="lob",
        company_id=resolved_company_id,
        result_count=len(pieces),
    )
    return DirectMailPieceListResponse(pieces=pieces)


@router.get("/postcards/{piece_id}", response_model=DirectMailPieceResponse)
async def get_postcard(
    piece_id: str,
    request: Request,
    auth: AuthContext = Depends(get_current_auth),
):
    request_id = _request_id(request)
    incr_metric("direct_mail.requests.received", operation="get_postcard", provider="lob")
    row = _get_piece_for_auth(auth, piece_id=piece_id, piece_type="postcard")
    provider = _get_provider_by_id(row["provider_id"])
    _ensure_lob_provider(provider["slug"], operation="get_postcard", request_id=request_id)
    creds = _get_org_provider_config(auth.org_id, "lob")

    try:
        provider_piece = lob_get_postcard(
            api_key=creds["api_key"],
            base_url=creds.get("instance_url"),
            postcard_id=piece_id,
        )
    except LobProviderError as exc:
        _raise_provider_http_error("get_postcard", exc, request_id=request_id)

    _upsert_piece(
        org_id=auth.org_id,
        company_id=row["company_id"],
        provider_id=row["provider_id"],
        piece_type="postcard",
        provider_piece=provider_piece,
    )
    response = _piece_row_to_response(_get_piece_for_auth(auth, piece_id=piece_id, piece_type="postcard"))
    incr_metric("direct_mail.requests.processed", operation="get_postcard", provider="lob")
    log_event(
        "direct_mail_operation_processed",
        request_id=request_id,
        operation="get_postcard",
        provider="lob",
        company_id=row["company_id"],
        piece_id=piece_id,
        status=response.status,
    )
    return response


@router.post("/postcards/{piece_id}/cancel", response_model=DirectMailPieceCancelResponse)
async def cancel_postcard(
    piece_id: str,
    request: Request,
    auth: AuthContext = Depends(get_current_auth),
):
    request_id = _request_id(request)
    incr_metric("direct_mail.requests.received", operation="cancel_postcard", provider="lob")
    row = _get_piece_for_auth(auth, piece_id=piece_id, piece_type="postcard")
    provider = _get_provider_by_id(row["provider_id"])
    _ensure_lob_provider(provider["slug"], operation="cancel_postcard", request_id=request_id)
    creds = _get_org_provider_config(auth.org_id, "lob")

    try:
        provider_piece = lob_cancel_postcard(
            api_key=creds["api_key"],
            base_url=creds.get("instance_url"),
            postcard_id=piece_id,
        )
    except LobProviderError as exc:
        _raise_provider_http_error("cancel_postcard", exc, request_id=request_id)

    _upsert_piece(
        org_id=auth.org_id,
        company_id=row["company_id"],
        provider_id=row["provider_id"],
        piece_type="postcard",
        provider_piece=provider_piece,
    )
    updated = _get_piece_for_auth(auth, piece_id=piece_id, piece_type="postcard")
    incr_metric("direct_mail.requests.processed", operation="cancel_postcard", provider="lob")
    log_event(
        "direct_mail_operation_processed",
        request_id=request_id,
        operation="cancel_postcard",
        provider="lob",
        company_id=row["company_id"],
        piece_id=piece_id,
        status=updated.get("status"),
    )
    return DirectMailPieceCancelResponse(
        id=updated["external_piece_id"],
        type="postcard",
        status=updated.get("status") or "unknown",
        updated_at=_parse_datetime(updated.get("updated_at")) or datetime.now(timezone.utc),
    )


@router.post("/letters", response_model=DirectMailPieceResponse, status_code=status.HTTP_201_CREATED)
async def create_letter(
    data: DirectMailPieceCreateRequest,
    request: Request,
    auth: AuthContext = Depends(get_current_auth),
):
    request_id = _request_id(request)
    incr_metric("direct_mail.requests.received", operation="create_letter", provider="lob")
    resolved_company_id = _resolve_company_id(auth, data.company_id)
    _get_company(auth, resolved_company_id)
    entitlement = _get_direct_mail_entitlement(auth.org_id, resolved_company_id)
    provider = _get_provider_by_id(entitlement["provider_id"])
    _ensure_lob_provider(provider["slug"], operation="create_letter", request_id=request_id)
    creds = _get_org_provider_config(auth.org_id, "lob")

    try:
        provider_piece = lob_create_letter(
            api_key=creds["api_key"],
            base_url=creds.get("instance_url"),
            payload=data.payload,
            idempotency_key=data.idempotency_key,
            idempotency_in_query=(data.idempotency_location == "query"),
        )
    except LobProviderError as exc:
        _raise_provider_http_error("create_letter", exc, request_id=request_id)

    if not provider_piece.get("id"):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Letter create failed: provider did not return piece id",
        )

    _upsert_piece(
        org_id=auth.org_id,
        company_id=resolved_company_id,
        provider_id=provider["id"],
        piece_type="letter",
        provider_piece=provider_piece,
    )
    row = _get_piece_for_auth(auth, piece_id=str(provider_piece["id"]), piece_type="letter")
    incr_metric("direct_mail.requests.processed", operation="create_letter", provider="lob")
    log_event(
        "direct_mail_operation_processed",
        request_id=request_id,
        operation="create_letter",
        provider="lob",
        company_id=resolved_company_id,
        piece_id=str(provider_piece["id"]),
        status=row.get("status"),
    )
    return _piece_row_to_response(row)


@router.get("/letters", response_model=DirectMailPieceListResponse)
async def list_letters(
    request: Request,
    company_id: str | None = Query(None),
    auth: AuthContext = Depends(get_current_auth),
):
    request_id = _request_id(request)
    incr_metric("direct_mail.requests.received", operation="list_letters", provider="lob")
    resolved_company_id = _resolve_company_id(auth, company_id)
    _get_company(auth, resolved_company_id)
    entitlement = _get_direct_mail_entitlement(auth.org_id, resolved_company_id)
    provider = _get_provider_by_id(entitlement["provider_id"])
    _ensure_lob_provider(provider["slug"], operation="list_letters", request_id=request_id)
    creds = _get_org_provider_config(auth.org_id, "lob")

    try:
        provider_payload = lob_list_letters(
            api_key=creds["api_key"],
            base_url=creds.get("instance_url"),
            params={"limit": 100},
        )
    except LobProviderError as exc:
        _raise_provider_http_error("list_letters", exc, request_id=request_id)

    for piece in _extract_piece_list_payload(provider_payload):
        _upsert_piece(
            org_id=auth.org_id,
            company_id=resolved_company_id,
            provider_id=provider["id"],
            piece_type="letter",
            provider_piece=piece,
        )

    rows = supabase.table("company_direct_mail_pieces").select("*").eq(
        "org_id", auth.org_id
    ).eq("company_id", resolved_company_id).eq("piece_type", "letter").is_("deleted_at", "null").execute().data or []
    pieces = [_piece_row_to_response(row) for row in rows]
    incr_metric("direct_mail.requests.processed", operation="list_letters", provider="lob")
    log_event(
        "direct_mail_operation_processed",
        request_id=request_id,
        operation="list_letters",
        provider="lob",
        company_id=resolved_company_id,
        result_count=len(pieces),
    )
    return DirectMailPieceListResponse(pieces=pieces)


@router.get("/letters/{piece_id}", response_model=DirectMailPieceResponse)
async def get_letter(
    piece_id: str,
    request: Request,
    auth: AuthContext = Depends(get_current_auth),
):
    request_id = _request_id(request)
    incr_metric("direct_mail.requests.received", operation="get_letter", provider="lob")
    row = _get_piece_for_auth(auth, piece_id=piece_id, piece_type="letter")
    provider = _get_provider_by_id(row["provider_id"])
    _ensure_lob_provider(provider["slug"], operation="get_letter", request_id=request_id)
    creds = _get_org_provider_config(auth.org_id, "lob")

    try:
        provider_piece = lob_get_letter(
            api_key=creds["api_key"],
            base_url=creds.get("instance_url"),
            letter_id=piece_id,
        )
    except LobProviderError as exc:
        _raise_provider_http_error("get_letter", exc, request_id=request_id)

    _upsert_piece(
        org_id=auth.org_id,
        company_id=row["company_id"],
        provider_id=row["provider_id"],
        piece_type="letter",
        provider_piece=provider_piece,
    )
    response = _piece_row_to_response(_get_piece_for_auth(auth, piece_id=piece_id, piece_type="letter"))
    incr_metric("direct_mail.requests.processed", operation="get_letter", provider="lob")
    log_event(
        "direct_mail_operation_processed",
        request_id=request_id,
        operation="get_letter",
        provider="lob",
        company_id=row["company_id"],
        piece_id=piece_id,
        status=response.status,
    )
    return response


@router.post("/letters/{piece_id}/cancel", response_model=DirectMailPieceCancelResponse)
async def cancel_letter(
    piece_id: str,
    request: Request,
    auth: AuthContext = Depends(get_current_auth),
):
    request_id = _request_id(request)
    incr_metric("direct_mail.requests.received", operation="cancel_letter", provider="lob")
    row = _get_piece_for_auth(auth, piece_id=piece_id, piece_type="letter")
    provider = _get_provider_by_id(row["provider_id"])
    _ensure_lob_provider(provider["slug"], operation="cancel_letter", request_id=request_id)
    creds = _get_org_provider_config(auth.org_id, "lob")

    try:
        provider_piece = lob_cancel_letter(
            api_key=creds["api_key"],
            base_url=creds.get("instance_url"),
            letter_id=piece_id,
        )
    except LobProviderError as exc:
        _raise_provider_http_error("cancel_letter", exc, request_id=request_id)

    _upsert_piece(
        org_id=auth.org_id,
        company_id=row["company_id"],
        provider_id=row["provider_id"],
        piece_type="letter",
        provider_piece=provider_piece,
    )
    updated = _get_piece_for_auth(auth, piece_id=piece_id, piece_type="letter")
    incr_metric("direct_mail.requests.processed", operation="cancel_letter", provider="lob")
    log_event(
        "direct_mail_operation_processed",
        request_id=request_id,
        operation="cancel_letter",
        provider="lob",
        company_id=row["company_id"],
        piece_id=piece_id,
        status=updated.get("status"),
    )
    return DirectMailPieceCancelResponse(
        id=updated["external_piece_id"],
        type="letter",
        status=updated.get("status") or "unknown",
        updated_at=_parse_datetime(updated.get("updated_at")) or datetime.now(timezone.utc),
    )


@router.post("/self-mailers", response_model=DirectMailPieceResponse, status_code=status.HTTP_201_CREATED)
async def create_self_mailer(
    data: DirectMailPieceCreateRequest,
    request: Request,
    auth: AuthContext = Depends(get_current_auth),
):
    request_id = _request_id(request)
    incr_metric("direct_mail.requests.received", operation="create_self_mailer", provider="lob")
    resolved_company_id = _resolve_company_id(auth, data.company_id)
    _get_company(auth, resolved_company_id)
    entitlement = _get_direct_mail_entitlement(auth.org_id, resolved_company_id)
    provider = _get_provider_by_id(entitlement["provider_id"])
    _ensure_lob_provider(provider["slug"], operation="create_self_mailer", request_id=request_id)
    creds = _get_org_provider_config(auth.org_id, "lob")

    try:
        provider_piece = lob_create_self_mailer(
            api_key=creds["api_key"],
            base_url=creds.get("instance_url"),
            payload=data.payload,
            idempotency_key=data.idempotency_key,
            idempotency_in_query=(data.idempotency_location == "query"),
        )
    except LobProviderError as exc:
        _raise_provider_http_error("create_self_mailer", exc, request_id=request_id)

    if not provider_piece.get("id"):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Self mailer create failed: provider did not return piece id",
        )

    _upsert_piece(
        org_id=auth.org_id,
        company_id=resolved_company_id,
        provider_id=provider["id"],
        piece_type="self_mailer",
        provider_piece=provider_piece,
    )
    row = _get_piece_for_auth(auth, piece_id=str(provider_piece["id"]), piece_type="self_mailer")
    incr_metric("direct_mail.requests.processed", operation="create_self_mailer", provider="lob")
    log_event(
        "direct_mail_operation_processed",
        request_id=request_id,
        operation="create_self_mailer",
        provider="lob",
        company_id=resolved_company_id,
        piece_id=str(provider_piece["id"]),
        status=row.get("status"),
    )
    return _piece_row_to_response(row)


@router.get("/self-mailers", response_model=DirectMailPieceListResponse)
async def list_self_mailers(
    request: Request,
    company_id: str | None = Query(None),
    auth: AuthContext = Depends(get_current_auth),
):
    request_id = _request_id(request)
    incr_metric("direct_mail.requests.received", operation="list_self_mailers", provider="lob")
    resolved_company_id = _resolve_company_id(auth, company_id)
    _get_company(auth, resolved_company_id)
    entitlement = _get_direct_mail_entitlement(auth.org_id, resolved_company_id)
    provider = _get_provider_by_id(entitlement["provider_id"])
    _ensure_lob_provider(provider["slug"], operation="list_self_mailers", request_id=request_id)
    creds = _get_org_provider_config(auth.org_id, "lob")

    try:
        provider_payload = lob_list_self_mailers(
            api_key=creds["api_key"],
            base_url=creds.get("instance_url"),
            params={"limit": 100},
        )
    except LobProviderError as exc:
        _raise_provider_http_error("list_self_mailers", exc, request_id=request_id)

    for piece in _extract_piece_list_payload(provider_payload):
        _upsert_piece(
            org_id=auth.org_id,
            company_id=resolved_company_id,
            provider_id=provider["id"],
            piece_type="self_mailer",
            provider_piece=piece,
        )

    rows = supabase.table("company_direct_mail_pieces").select("*").eq(
        "org_id", auth.org_id
    ).eq("company_id", resolved_company_id).eq("piece_type", "self_mailer").is_("deleted_at", "null").execute().data or []
    pieces = [_piece_row_to_response(row) for row in rows]
    incr_metric("direct_mail.requests.processed", operation="list_self_mailers", provider="lob")
    log_event(
        "direct_mail_operation_processed",
        request_id=request_id,
        operation="list_self_mailers",
        provider="lob",
        company_id=resolved_company_id,
        result_count=len(pieces),
    )
    return DirectMailPieceListResponse(pieces=pieces)


@router.get("/self-mailers/{piece_id}", response_model=DirectMailPieceResponse)
async def get_self_mailer(
    piece_id: str,
    request: Request,
    auth: AuthContext = Depends(get_current_auth),
):
    request_id = _request_id(request)
    incr_metric("direct_mail.requests.received", operation="get_self_mailer", provider="lob")
    row = _get_piece_for_auth(auth, piece_id=piece_id, piece_type="self_mailer")
    provider = _get_provider_by_id(row["provider_id"])
    _ensure_lob_provider(provider["slug"], operation="get_self_mailer", request_id=request_id)
    creds = _get_org_provider_config(auth.org_id, "lob")

    try:
        provider_piece = lob_get_self_mailer(
            api_key=creds["api_key"],
            base_url=creds.get("instance_url"),
            self_mailer_id=piece_id,
        )
    except LobProviderError as exc:
        _raise_provider_http_error("get_self_mailer", exc, request_id=request_id)

    _upsert_piece(
        org_id=auth.org_id,
        company_id=row["company_id"],
        provider_id=row["provider_id"],
        piece_type="self_mailer",
        provider_piece=provider_piece,
    )
    response = _piece_row_to_response(_get_piece_for_auth(auth, piece_id=piece_id, piece_type="self_mailer"))
    incr_metric("direct_mail.requests.processed", operation="get_self_mailer", provider="lob")
    log_event(
        "direct_mail_operation_processed",
        request_id=request_id,
        operation="get_self_mailer",
        provider="lob",
        company_id=row["company_id"],
        piece_id=piece_id,
        status=response.status,
    )
    return response


@router.post("/self-mailers/{piece_id}/cancel", response_model=DirectMailPieceCancelResponse)
async def cancel_self_mailer(
    piece_id: str,
    request: Request,
    auth: AuthContext = Depends(get_current_auth),
):
    request_id = _request_id(request)
    incr_metric("direct_mail.requests.received", operation="cancel_self_mailer", provider="lob")
    row = _get_piece_for_auth(auth, piece_id=piece_id, piece_type="self_mailer")
    provider = _get_provider_by_id(row["provider_id"])
    _ensure_lob_provider(provider["slug"], operation="cancel_self_mailer", request_id=request_id)
    creds = _get_org_provider_config(auth.org_id, "lob")

    try:
        provider_piece = lob_cancel_self_mailer(
            api_key=creds["api_key"],
            base_url=creds.get("instance_url"),
            self_mailer_id=piece_id,
        )
    except LobProviderError as exc:
        _raise_provider_http_error("cancel_self_mailer", exc, request_id=request_id)

    _upsert_piece(
        org_id=auth.org_id,
        company_id=row["company_id"],
        provider_id=row["provider_id"],
        piece_type="self_mailer",
        provider_piece=provider_piece,
    )
    updated = _get_piece_for_auth(auth, piece_id=piece_id, piece_type="self_mailer")
    incr_metric("direct_mail.requests.processed", operation="cancel_self_mailer", provider="lob")
    log_event(
        "direct_mail_operation_processed",
        request_id=request_id,
        operation="cancel_self_mailer",
        provider="lob",
        company_id=row["company_id"],
        piece_id=piece_id,
        status=updated.get("status"),
    )
    return DirectMailPieceCancelResponse(
        id=updated["external_piece_id"],
        type="self_mailer",
        status=updated.get("status") or "unknown",
        updated_at=_parse_datetime(updated.get("updated_at")) or datetime.now(timezone.utc),
    )


@router.post("/checks", response_model=DirectMailPieceResponse, status_code=status.HTTP_201_CREATED)
async def create_check(
    data: DirectMailPieceCreateRequest,
    request: Request,
    auth: AuthContext = Depends(get_current_auth),
):
    request_id = _request_id(request)
    incr_metric("direct_mail.requests.received", operation="create_check", provider="lob")
    resolved_company_id = _resolve_company_id(auth, data.company_id)
    _get_company(auth, resolved_company_id)
    entitlement = _get_direct_mail_entitlement(auth.org_id, resolved_company_id)
    provider = _get_provider_by_id(entitlement["provider_id"])
    _ensure_lob_provider(provider["slug"], operation="create_check", request_id=request_id)
    creds = _get_org_provider_config(auth.org_id, "lob")

    try:
        provider_piece = lob_create_check(
            api_key=creds["api_key"],
            base_url=creds.get("instance_url"),
            payload=data.payload,
            idempotency_key=data.idempotency_key,
            idempotency_in_query=(data.idempotency_location == "query"),
        )
    except LobProviderError as exc:
        _raise_provider_http_error("create_check", exc, request_id=request_id)

    if not provider_piece.get("id"):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Check create failed: provider did not return piece id",
        )

    _upsert_piece(
        org_id=auth.org_id,
        company_id=resolved_company_id,
        provider_id=provider["id"],
        piece_type="check",
        provider_piece=provider_piece,
    )
    row = _get_piece_for_auth(auth, piece_id=str(provider_piece["id"]), piece_type="check")
    incr_metric("direct_mail.requests.processed", operation="create_check", provider="lob")
    log_event(
        "direct_mail_operation_processed",
        request_id=request_id,
        operation="create_check",
        provider="lob",
        company_id=resolved_company_id,
        piece_id=str(provider_piece["id"]),
        status=row.get("status"),
    )
    return _piece_row_to_response(row)


@router.get("/checks", response_model=DirectMailPieceListResponse)
async def list_checks(
    request: Request,
    company_id: str | None = Query(None),
    auth: AuthContext = Depends(get_current_auth),
):
    request_id = _request_id(request)
    incr_metric("direct_mail.requests.received", operation="list_checks", provider="lob")
    resolved_company_id = _resolve_company_id(auth, company_id)
    _get_company(auth, resolved_company_id)
    entitlement = _get_direct_mail_entitlement(auth.org_id, resolved_company_id)
    provider = _get_provider_by_id(entitlement["provider_id"])
    _ensure_lob_provider(provider["slug"], operation="list_checks", request_id=request_id)
    creds = _get_org_provider_config(auth.org_id, "lob")

    try:
        provider_payload = lob_list_checks(
            api_key=creds["api_key"],
            base_url=creds.get("instance_url"),
            params={"limit": 100},
        )
    except LobProviderError as exc:
        _raise_provider_http_error("list_checks", exc, request_id=request_id)

    for piece in _extract_piece_list_payload(provider_payload):
        _upsert_piece(
            org_id=auth.org_id,
            company_id=resolved_company_id,
            provider_id=provider["id"],
            piece_type="check",
            provider_piece=piece,
        )

    rows = supabase.table("company_direct_mail_pieces").select("*").eq(
        "org_id", auth.org_id
    ).eq("company_id", resolved_company_id).eq("piece_type", "check").is_("deleted_at", "null").execute().data or []
    pieces = [_piece_row_to_response(row) for row in rows]
    incr_metric("direct_mail.requests.processed", operation="list_checks", provider="lob")
    log_event(
        "direct_mail_operation_processed",
        request_id=request_id,
        operation="list_checks",
        provider="lob",
        company_id=resolved_company_id,
        result_count=len(pieces),
    )
    return DirectMailPieceListResponse(pieces=pieces)


@router.get("/checks/{piece_id}", response_model=DirectMailPieceResponse)
async def get_check(
    piece_id: str,
    request: Request,
    auth: AuthContext = Depends(get_current_auth),
):
    request_id = _request_id(request)
    incr_metric("direct_mail.requests.received", operation="get_check", provider="lob")
    row = _get_piece_for_auth(auth, piece_id=piece_id, piece_type="check")
    provider = _get_provider_by_id(row["provider_id"])
    _ensure_lob_provider(provider["slug"], operation="get_check", request_id=request_id)
    creds = _get_org_provider_config(auth.org_id, "lob")

    try:
        provider_piece = lob_get_check(
            api_key=creds["api_key"],
            base_url=creds.get("instance_url"),
            check_id=piece_id,
        )
    except LobProviderError as exc:
        _raise_provider_http_error("get_check", exc, request_id=request_id)

    _upsert_piece(
        org_id=auth.org_id,
        company_id=row["company_id"],
        provider_id=row["provider_id"],
        piece_type="check",
        provider_piece=provider_piece,
    )
    response = _piece_row_to_response(_get_piece_for_auth(auth, piece_id=piece_id, piece_type="check"))
    incr_metric("direct_mail.requests.processed", operation="get_check", provider="lob")
    log_event(
        "direct_mail_operation_processed",
        request_id=request_id,
        operation="get_check",
        provider="lob",
        company_id=row["company_id"],
        piece_id=piece_id,
        status=response.status,
    )
    return response


@router.post("/checks/{piece_id}/cancel", response_model=DirectMailPieceCancelResponse)
async def cancel_check(
    piece_id: str,
    request: Request,
    auth: AuthContext = Depends(get_current_auth),
):
    request_id = _request_id(request)
    incr_metric("direct_mail.requests.received", operation="cancel_check", provider="lob")
    row = _get_piece_for_auth(auth, piece_id=piece_id, piece_type="check")
    provider = _get_provider_by_id(row["provider_id"])
    _ensure_lob_provider(provider["slug"], operation="cancel_check", request_id=request_id)
    creds = _get_org_provider_config(auth.org_id, "lob")

    try:
        provider_piece = lob_cancel_check(
            api_key=creds["api_key"],
            base_url=creds.get("instance_url"),
            check_id=piece_id,
        )
    except LobProviderError as exc:
        _raise_provider_http_error("cancel_check", exc, request_id=request_id)

    _upsert_piece(
        org_id=auth.org_id,
        company_id=row["company_id"],
        provider_id=row["provider_id"],
        piece_type="check",
        provider_piece=provider_piece,
    )
    updated = _get_piece_for_auth(auth, piece_id=piece_id, piece_type="check")
    incr_metric("direct_mail.requests.processed", operation="cancel_check", provider="lob")
    log_event(
        "direct_mail_operation_processed",
        request_id=request_id,
        operation="cancel_check",
        provider="lob",
        company_id=row["company_id"],
        piece_id=piece_id,
        status=updated.get("status"),
    )
    return DirectMailPieceCancelResponse(
        id=updated["external_piece_id"],
        type="check",
        status=updated.get("status") or "unknown",
        updated_at=_parse_datetime(updated.get("updated_at")) or datetime.now(timezone.utc),
    )
