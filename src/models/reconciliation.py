from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ReconciliationRunRequest(BaseModel):
    provider_slug: Literal["smartlead", "heyreach", "emailbison"] | None = None
    org_id: str | None = None
    company_id: str | None = None
    dry_run: bool = True
    campaign_limit: int = Field(default=100, ge=1, le=1000)
    lead_limit: int = Field(default=500, ge=1, le=2000)
    sync_messages: bool = True
    message_limit: int = Field(default=1000, ge=1, le=5000)


class ReconciliationProviderStats(BaseModel):
    provider_slug: Literal["smartlead", "heyreach", "emailbison"]
    companies_scanned: int
    campaigns_scanned: int
    campaigns_created: int
    campaigns_updated: int
    leads_scanned: int
    leads_created: int
    leads_updated: int
    messages_scanned: int
    messages_created: int
    messages_updated: int
    errors: list[str] = []


class ReconciliationRunResponse(BaseModel):
    dry_run: bool
    started_at: datetime
    finished_at: datetime
    providers: list[ReconciliationProviderStats]


class EmailBisonWebhookBackfillRequest(BaseModel):
    org_id: str | None = None
    company_id: str | None = None
    dry_run: bool = True
    lookback_hours: int = Field(default=24, ge=1, le=168)
    cursor_ts: datetime | None = None
    campaign_limit: int = Field(default=200, ge=1, le=1000)


class EmailBisonWebhookBackfillResponse(BaseModel):
    dry_run: bool
    started_at: datetime
    finished_at: datetime
    cursor_start: datetime
    cursor_end: datetime
    campaigns_scanned: int
    campaigns_updated: int
    leads_updated: int
    messages_upserted: int
    errors: list[str] = []
    notes: list[str] = []
