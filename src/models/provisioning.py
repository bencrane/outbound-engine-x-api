from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class EmailOutreachProvisionRequest(BaseModel):
    smartlead_client_id: int | None = Field(
        default=None,
        description="Existing Smartlead client ID to bind this company to",
    )


class EmailOutreachProvisionResponse(BaseModel):
    company_id: str
    org_id: str
    capability: Literal["email_outreach"]
    provider: str
    entitlement_status: Literal["entitled", "connected", "disconnected"]
    provisioning_state: Literal["pending_client_mapping", "connected", "failed"]
    smartlead_client_id: int | None = None
    last_error: str | None = None
    updated_at: datetime
