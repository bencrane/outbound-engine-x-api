from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class EmailOutreachProvisionRequest(BaseModel):
    provider: Literal["smartlead", "emailbison"] = Field(
        default="smartlead",
        description="Email outreach provider to provision for this company",
    )
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


class DirectMailProvisionRequest(BaseModel):
    provider: Literal["lob"] = Field(
        default="lob",
        description="Direct mail provider to provision for this company",
    )


class DirectMailProvisionResponse(BaseModel):
    company_id: str
    org_id: str
    capability: Literal["direct_mail"]
    provider: Literal["lob"]
    entitlement_status: Literal["entitled", "connected", "disconnected"]
    provisioning_state: Literal["connected", "failed"]
    last_error: str | None = None
    updated_at: datetime
