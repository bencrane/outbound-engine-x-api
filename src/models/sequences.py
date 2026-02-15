from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class CampaignSequenceUpsertRequest(BaseModel):
    sequence: list[dict[str, Any]] = Field(default_factory=list)

    model_config = {
        "json_schema_extra": {
            "example": {
                "sequence": [
                    {
                        "seq_number": 1,
                        "subject": "Quick question",
                        "email_body": "Hi {{first_name}}, ...",
                        "seq_delay_details": {"delay_in_days": 0},
                    }
                ]
            }
        }
    }


class CampaignSequenceResponse(BaseModel):
    campaign_id: str
    sequence: list[dict[str, Any]]
    source: str
    version: int | None = None
    updated_at: datetime
