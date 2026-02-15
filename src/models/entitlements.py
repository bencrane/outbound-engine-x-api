from pydantic import BaseModel
from datetime import datetime
from typing import Any


class EntitlementCreate(BaseModel):
    company_id: str
    capability_id: str
    provider_id: str


class EntitlementUpdate(BaseModel):
    status: str | None = None
    provider_config: dict[str, Any] | None = None


class EntitlementResponse(BaseModel):
    id: str
    company_id: str
    capability_id: str
    provider_id: str
    status: str
    provider_config: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
