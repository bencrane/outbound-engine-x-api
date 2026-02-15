from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from src.models.campaigns import CampaignResponse
from src.models.leads import CampaignLeadResponse, LeadCreateInput
from src.models.messages import CampaignMessageResponse


LinkedinCampaignAction = Literal["pause", "resume"]
LinkedinLeadStatus = Literal["pending", "contacted", "replied", "connected", "not_interested", "bounced"]


class LinkedinCampaignCreateRequest(BaseModel):
    name: str
    company_id: str | None = None
    description: str | None = None
    daily_limit: int | None = None
    delay_between_actions: int | None = None


class LinkedinCampaignActionRequest(BaseModel):
    action: LinkedinCampaignAction


class LinkedinCampaignLeadsAddRequest(BaseModel):
    leads: list[LeadCreateInput]


class LinkedinLeadStatusUpdateRequest(BaseModel):
    status: LinkedinLeadStatus


class LinkedinSendMessageRequest(BaseModel):
    message: str
    template_id: str | None = None


class LinkedinCampaignMetricsResponse(BaseModel):
    campaign_id: str
    provider: Literal["heyreach"]
    provider_campaign_id: str
    normalized: dict[str, int | float | None]
    raw: dict
    fetched_at: datetime


class LinkedinCampaignResponse(CampaignResponse):
    pass


class LinkedinCampaignLeadResponse(CampaignLeadResponse):
    pass


class LinkedinCampaignMessageResponse(CampaignMessageResponse):
    pass
