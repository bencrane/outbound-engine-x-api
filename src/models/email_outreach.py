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


class EmailOutreachWorkspaceStatsRequest(BaseModel):
    start_date: str
    end_date: str


class EmailOutreachWorkspaceMasterInboxSettingsUpdateRequest(BaseModel):
    sync_all_emails: bool | None = None
    smart_warmup_filter: bool | None = None
    auto_interested_categorization: bool | None = None


class EmailOutreachCampaignEventsStatsRequest(BaseModel):
    start_date: str
    end_date: str
    campaign_ids: list[str] | None = None
    inbox_ids: list[str] | None = None
