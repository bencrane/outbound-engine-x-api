from __future__ import annotations

from datetime import datetime
from typing import Literal, Any

from pydantic import BaseModel


class InboxResponse(BaseModel):
    id: str
    company_id: str
    provider_id: str
    external_account_id: str
    email: str
    display_name: str | None = None
    status: Literal["active", "inactive"]
    warmup_enabled: bool | None = None
    updated_at: datetime


class InboxSyncResponse(BaseModel):
    company_id: str
    synced_count: int
    skipped_count: int
    smartlead_client_id: int
    updated_at: datetime
    warnings: list[str] = []


class InboxSenderEmailUpdateRequest(BaseModel):
    daily_limit: int | None = None
    name: str | None = None
    email_signature: str | None = None


class InboxSenderEmailDetailResponse(BaseModel):
    inbox_id: str
    provider: str
    sender_email: dict[str, Any]


class InboxWarmupDetailRequest(BaseModel):
    start_date: str
    end_date: str


class InboxWarmupBulkToggleRequest(BaseModel):
    inbox_ids: list[str]


class InboxWarmupBulkLimitRequest(BaseModel):
    inbox_ids: list[str]
    daily_limit: int
    daily_reply_limit: int | str | None = None


class InboxWarmupResponse(BaseModel):
    inbox_id: str
    provider: str
    warmup: dict[str, Any]


class InboxHealthcheckResponse(BaseModel):
    inbox_id: str
    provider: str
    healthcheck: dict[str, Any]
