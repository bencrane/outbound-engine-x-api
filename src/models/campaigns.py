from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


CampaignStatus = Literal["DRAFTED", "ACTIVE", "PAUSED", "STOPPED", "COMPLETED"]


class CampaignCreateRequest(BaseModel):
    name: str
    company_id: str | None = None


class CampaignStatusUpdateRequest(BaseModel):
    status: CampaignStatus


class CampaignResponse(BaseModel):
    id: str
    company_id: str
    provider_id: str
    external_campaign_id: str
    name: str
    status: CampaignStatus
    created_by_user_id: str | None = None
    created_at: datetime
    updated_at: datetime
