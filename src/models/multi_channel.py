from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field

SequenceChannel = Literal["email", "linkedin", "direct_mail", "voicemail"]
SequenceExecutionMode = Literal["direct_single_touch", "campaign_mediated"]
SequenceActionType = Literal[
    "send_email",
    "send_connection_request",
    "send_linkedin_message",
    "send_postcard",
    "send_letter",
    "send_voicemail",
]
LeadStepStatus = Literal[
    "pending",
    "executing",
    "executed",
    "skipped",
    "failed",
    "completed",
]


class SequenceStepDefinition(BaseModel):
    step_order: int = Field(ge=1)
    channel: SequenceChannel
    action_type: SequenceActionType
    action_config: dict[str, Any] = Field(default_factory=dict)
    delay_days: int = Field(default=0, ge=0)
    execution_mode: SequenceExecutionMode = "direct_single_touch"
    skip_if: dict[str, Any] | None = None
    provider_campaign_id: str | None = None

    model_config = {"extra": "forbid"}


class SequenceStepResponse(SequenceStepDefinition):
    id: str
    provider_id: str
    created_at: datetime
    updated_at: datetime


class LeadProgressResponse(BaseModel):
    id: str
    lead_id: str
    current_step_order: int = Field(ge=1)
    step_status: LeadStepStatus
    next_execute_at: datetime | None = None
    executed_at: datetime | None = None
    completed_at: datetime | None = None
    attempts: int = Field(default=0, ge=0)
    last_error: str | None = None

    model_config = {"extra": "forbid"}


class LeadProviderIdResponse(BaseModel):
    provider_id: str
    provider_slug: str
    external_id: str

    model_config = {"extra": "forbid"}


class MultiChannelCampaignCreateRequest(BaseModel):
    campaign_type: Literal["multi_channel"] = "multi_channel"
    company_id: str | None = None
    name: str

    model_config = {"extra": "forbid"}


class MultiChannelSequenceUpsertRequest(BaseModel):
    steps: list[SequenceStepDefinition] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class LeadStepContent(BaseModel):
    step_order: int = Field(ge=1)
    action_config_override: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "forbid"}


class MultiChannelLeadCreateInput(BaseModel):
    email: EmailStr
    first_name: str | None = None
    last_name: str | None = None
    linkedin_url: str | None = None
    company: str | None = None
    title: str | None = None
    phone: str | None = None
    step_content: list[LeadStepContent] | None = None

    model_config = {"extra": "forbid"}


class MultiChannelLeadsAddRequest(BaseModel):
    leads: list[MultiChannelLeadCreateInput] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class LeadStepContentUpsertRequest(BaseModel):
    steps: list[LeadStepContent] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class LeadStepContentResponse(BaseModel):
    step_order: int = Field(ge=1)
    action_config_override: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "forbid"}
