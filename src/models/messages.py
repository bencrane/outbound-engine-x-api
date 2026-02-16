from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class CampaignMessageResponse(BaseModel):
    id: str
    company_campaign_id: str
    company_campaign_lead_id: str | None = None
    external_message_id: str
    direction: Literal["inbound", "outbound", "unknown"]
    sequence_step_number: int | None = None
    subject: str | None = None
    body: str | None = None
    sent_at: datetime | None = None
    updated_at: datetime


class OrgCampaignMessageResponse(BaseModel):
    id: str
    company_id: str
    company_campaign_id: str
    company_campaign_lead_id: str | None = None
    external_message_id: str
    direction: Literal["inbound", "outbound", "unknown"]
    sequence_step_number: int | None = None
    subject: str | None = None
    body: str | None = None
    sent_at: datetime | None = None
    updated_at: datetime
