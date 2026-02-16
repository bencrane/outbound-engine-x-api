from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


DirectMailPieceType = Literal["postcard", "letter", "self_mailer", "check"]
DirectMailPieceStatus = Literal[
    "queued",
    "processing",
    "ready_for_mail",
    "in_transit",
    "delivered",
    "returned",
    "canceled",
    "failed",
    "unknown",
]
DirectMailAddressVerificationStatus = Literal["deliverable", "undeliverable", "corrected", "partial", "unknown"]


class DirectMailAddressVerificationUSRequest(BaseModel):
    payload: dict[str, Any]


class DirectMailAddressVerificationUSBulkRequest(BaseModel):
    payload: dict[str, Any]


class DirectMailAddressVerificationResponse(BaseModel):
    status: DirectMailAddressVerificationStatus
    deliverability: DirectMailAddressVerificationStatus
    normalized_address: dict[str, Any] | None = None
    raw_provider_status: str | None = None


class DirectMailPieceCreateRequest(BaseModel):
    payload: dict[str, Any]
    company_id: str | None = None
    idempotency_key: str | None = Field(default=None, min_length=1)
    idempotency_location: Literal["header", "query"] = "header"


class DirectMailPieceListResponse(BaseModel):
    pieces: list["DirectMailPieceResponse"]


class DirectMailPieceResponse(BaseModel):
    id: str
    type: DirectMailPieceType
    status: DirectMailPieceStatus
    created_at: datetime
    updated_at: datetime
    send_date: datetime | None = None
    metadata: dict[str, Any] | None = None
    provider: str | None = None


class DirectMailPieceCancelResponse(BaseModel):
    id: str
    type: DirectMailPieceType
    status: DirectMailPieceStatus
    updated_at: datetime
