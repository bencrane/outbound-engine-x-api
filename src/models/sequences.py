from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class CampaignSequenceUpsertRequest(BaseModel):
    sequence: list[dict[str, Any]] = Field(default_factory=list)


class CampaignSequenceResponse(BaseModel):
    campaign_id: str
    sequence: list[dict[str, Any]]
    source: str
    version: int | None = None
    updated_at: datetime
