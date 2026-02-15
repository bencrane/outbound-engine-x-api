from __future__ import annotations

from datetime import datetime
from typing import Literal, Any

from pydantic import BaseModel


class InboxResponse(BaseModel):
    id: str
    company_id: str
    provider_id: str
    external_account_id: str
    email: str
    display_name: str | None = None
    status: Literal["active", "inactive"]
    warmup_enabled: bool | None = None
    updated_at: datetime


class InboxSyncResponse(BaseModel):
    company_id: str
    synced_count: int
    skipped_count: int
    smartlead_client_id: int
    updated_at: datetime
    warnings: list[str] = []
