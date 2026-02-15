from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class CampaignAnalyticsSummaryResponse(BaseModel):
    campaign_id: str
    leads_total: int
    leads_active: int
    leads_paused: int
    leads_unsubscribed: int
    replies_total: int
    outbound_messages_total: int
    reply_rate: float
    campaign_status: str
    last_activity_at: datetime | None = None
    updated_at: datetime


class CampaignAnalyticsProviderResponse(BaseModel):
    campaign_id: str
    provider: str
    provider_campaign_id: str
    normalized: dict[str, Any]
    raw: dict[str, Any]
    fetched_at: datetime


class CampaignAnalyticsDashboardItem(BaseModel):
    campaign_id: str
    company_id: str
    campaign_name: str
    campaign_status: str
    leads_total: int
    replies_total: int
    outbound_messages_total: int
    reply_rate: float
    last_activity_at: datetime | None = None
    updated_at: datetime
