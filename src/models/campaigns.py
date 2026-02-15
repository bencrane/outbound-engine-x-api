from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


CampaignStatus = Literal["DRAFTED", "ACTIVE", "PAUSED", "STOPPED", "COMPLETED"]


class CampaignCreateRequest(BaseModel):
    name: str
    company_id: str | None = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "name": "Q2 Outbound - Agencies",
                "company_id": "c6c0a111-7f9f-4c3d-8f53-5a5a6ef7a111",
            }
        }
    }


class CampaignStatusUpdateRequest(BaseModel):
    status: CampaignStatus

    model_config = {
        "json_schema_extra": {
            "example": {"status": "ACTIVE"}
        }
    }


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
