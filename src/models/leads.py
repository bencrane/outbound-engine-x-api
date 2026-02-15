from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class LeadCreateInput(BaseModel):
    email: EmailStr
    first_name: str | None = None
    last_name: str | None = None
    linkedin_url: str | None = None
    company: str | None = None
    title: str | None = None
    phone: str | None = None


class CampaignLeadsAddRequest(BaseModel):
    leads: list[LeadCreateInput] = Field(default_factory=list)

    model_config = {
        "json_schema_extra": {
            "example": {
                "leads": [
                    {
                        "email": "alice@deltacorp.com",
                        "first_name": "Alice",
                        "last_name": "Smith",
                        "company": "Delta Corp",
                        "title": "Head of Growth",
                    }
                ]
            }
        }
    }


class CampaignLeadResponse(BaseModel):
    id: str
    company_campaign_id: str
    external_lead_id: str
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    company_name: str | None = None
    title: str | None = None
    status: Literal[
        "active",
        "paused",
        "unsubscribed",
        "replied",
        "bounced",
        "pending",
        "contacted",
        "connected",
        "not_interested",
        "unknown",
    ]
    category: str | None = None
    updated_at: datetime


class CampaignLeadMutationResponse(BaseModel):
    campaign_id: str
    affected: int
    status: Literal[
        "added",
        "paused",
        "active",
        "unsubscribed",
        "pending",
        "contacted",
        "connected",
        "not_interested",
        "bounced",
        "unknown",
    ]
