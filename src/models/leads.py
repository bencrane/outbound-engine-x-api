from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class LeadCreateInput(BaseModel):
    email: EmailStr
    first_name: str | None = None
    last_name: str | None = None
    company: str | None = None
    title: str | None = None
    phone: str | None = None


class CampaignLeadsAddRequest(BaseModel):
    leads: list[LeadCreateInput] = Field(default_factory=list)


class CampaignLeadResponse(BaseModel):
    id: str
    company_campaign_id: str
    external_lead_id: str
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    company_name: str | None = None
    title: str | None = None
    status: str
    category: str | None = None
    updated_at: datetime


class CampaignLeadMutationResponse(BaseModel):
    campaign_id: str
    affected: int
    status: str
