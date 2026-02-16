from __future__ import annotations

from pydantic import BaseModel


class EmailOutreachTagCreateRequest(BaseModel):
    name: str
    default: bool | None = None


class EmailOutreachTagAttachCampaignsRequest(BaseModel):
    tag_ids: list[int]
    campaign_ids: list[str]
    skip_webhooks: bool | None = None


class EmailOutreachTagAttachLeadsRequest(BaseModel):
    tag_ids: list[int]
    campaign_id: str
    lead_ids: list[str]
    skip_webhooks: bool | None = None


class EmailOutreachTagAttachInboxesRequest(BaseModel):
    tag_ids: list[int]
    inbox_ids: list[str]
    skip_webhooks: bool | None = None


class EmailOutreachCustomVariableCreateRequest(BaseModel):
    name: str


class EmailOutreachBlocklistEmailCreateRequest(BaseModel):
    email: str


class EmailOutreachBlocklistEmailsBulkCreateRequest(BaseModel):
    emails: list[str]


class EmailOutreachBlocklistDomainCreateRequest(BaseModel):
    domain: str


class EmailOutreachBlocklistDomainsBulkCreateRequest(BaseModel):
    domains: list[str]
