from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class WebhookEventListItem(BaseModel):
    id: str
    provider_slug: Literal["smartlead", "heyreach"]
    event_key: str
    event_type: str | None = None
    status: Literal["processed", "replayed", "failed", "dead_letter"] | None = None
    org_id: str | None = None
    company_id: str | None = None
    replay_count: int | None = None
    last_replay_at: datetime | None = None
    last_error: str | None = None
    processed_at: datetime | None = None
    created_at: datetime | None = None


class WebhookReplayResponse(BaseModel):
    status: Literal["replayed"]
    provider_slug: Literal["smartlead", "heyreach"]
    event_key: str
    event_type: str


class WebhookReplayBulkRequest(BaseModel):
    provider_slug: Literal["smartlead", "heyreach"]
    event_keys: list[str] = Field(default_factory=list, max_length=100)


class WebhookReplayBulkItem(BaseModel):
    event_key: str
    status: Literal["replayed", "not_found"]
    event_type: str | None = None


class WebhookReplayBulkResponse(BaseModel):
    provider_slug: Literal["smartlead", "heyreach"]
    requested: int
    replayed: int
    not_found: int
    results: list[WebhookReplayBulkItem]


class WebhookReplayQueryRequest(BaseModel):
    provider_slug: Literal["smartlead", "heyreach"]
    event_type: str | None = None
    org_id: str | None = None
    company_id: str | None = None
    from_ts: datetime | None = None
    to_ts: datetime | None = None
    limit: int = Field(default=50, ge=1, le=200)


class WebhookReplayQueryResponse(BaseModel):
    provider_slug: Literal["smartlead", "heyreach"]
    matched: int
    replayed: int
    results: list[WebhookReplayBulkItem]
