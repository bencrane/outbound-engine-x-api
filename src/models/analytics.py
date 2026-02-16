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


class ClientAnalyticsRollupItem(BaseModel):
    company_id: str
    campaigns_total: int
    leads_total: int
    outbound_messages_total: int
    replies_total: int
    reply_rate: float
    last_activity_at: datetime | None = None
    updated_at: datetime


class ReliabilityByProviderItem(BaseModel):
    provider_slug: str
    events_total: int
    replayed_events_total: int
    replay_count_total: int
    errors_total: int


class ReliabilityAnalyticsResponse(BaseModel):
    company_id: str | None = None
    events_total: int
    replayed_events_total: int
    replay_count_total: int
    errors_total: int
    by_provider: list[ReliabilityByProviderItem]
    from_ts: datetime | None = None
    to_ts: datetime | None = None
    updated_at: datetime


class MessageSyncHealthItem(BaseModel):
    company_id: str
    campaign_id: str
    campaign_name: str
    campaign_status: str
    provider_id: str
    message_sync_status: str | None = None
    last_message_sync_at: datetime | None = None
    last_message_sync_error: str | None = None
    leads_total: int
    messages_total: int
    inbound_total: int
    outbound_total: int
    updated_at: datetime


class SequenceStepPerformanceItem(BaseModel):
    campaign_id: str
    sequence_step_number: int
    outbound_messages_total: int
    replies_total: int
    reply_rate: float
    last_activity_at: datetime | None = None
    updated_at: datetime


class DirectMailVolumeByTypeStatusItem(BaseModel):
    piece_type: str
    status: str
    count: int


class DirectMailFunnelItem(BaseModel):
    stage: str
    count: int


class DirectMailReasonBreakdownItem(BaseModel):
    reason: str
    count: int


class DirectMailDailyTrendItem(BaseModel):
    day: str
    created: int
    processed: int
    in_transit: int
    delivered: int
    returned: int
    failed: int


class DirectMailAnalyticsResponse(BaseModel):
    org_id: str
    company_id: str | None = None
    all_companies: bool = False
    from_ts: datetime
    to_ts: datetime
    total_pieces: int
    volume_by_type_status: list[DirectMailVolumeByTypeStatusItem]
    delivery_funnel: list[DirectMailFunnelItem]
    failure_reason_breakdown: list[DirectMailReasonBreakdownItem]
    daily_trends: list[DirectMailDailyTrendItem]
    updated_at: datetime
