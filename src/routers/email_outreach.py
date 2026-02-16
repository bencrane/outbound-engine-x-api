from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from src.auth import AuthContext, get_current_auth
from src.db import supabase
from src.domain.provider_errors import provider_error_detail, provider_error_http_status
from src.models.email_outreach import (
    EmailOutreachBlocklistDomainCreateRequest,
    EmailOutreachBlocklistDomainsBulkCreateRequest,
    EmailOutreachBlocklistEmailCreateRequest,
    EmailOutreachBlocklistEmailsBulkCreateRequest,
    EmailOutreachBulkCampaignDeleteRequest,
    EmailOutreachBulkInboxDailyLimitUpdateRequest,
    EmailOutreachBulkInboxesCreateRequest,
    EmailOutreachBulkInboxSignatureUpdateRequest,
    EmailOutreachBulkLeadDeleteRequest,
    EmailOutreachBulkLeadStatusUpdateRequest,
    EmailOutreachBulkLeadsCsvCreateRequest,
    EmailOutreachCampaignEventsStatsRequest,
    EmailOutreachCustomVariableCreateRequest,
    EmailOutreachTagAttachCampaignsRequest,
    EmailOutreachTagAttachInboxesRequest,
    EmailOutreachTagAttachLeadsRequest,
    EmailOutreachTagCreateRequest,
    EmailOutreachWebhookCreateRequest,
    EmailOutreachWebhookSamplePayloadRequest,
    EmailOutreachWebhookTestEventRequest,
    EmailOutreachWebhookUpdateRequest,
    EmailOutreachWorkspaceMasterInboxSettingsUpdateRequest,
    EmailOutreachWorkspaceStatsRequest,
)
from src.providers.emailbison.client import (
    EmailBisonProviderError,
    attach_tags_to_campaigns as emailbison_attach_tags_to_campaigns,
    attach_tags_to_leads as emailbison_attach_tags_to_leads,
    attach_tags_to_sender_emails as emailbison_attach_tags_to_sender_emails,
    bulk_create_leads_csv as emailbison_bulk_create_leads_csv,
    bulk_create_sender_emails as emailbison_bulk_create_sender_emails,
    bulk_delete_campaigns as emailbison_bulk_delete_campaigns,
    bulk_delete_leads as emailbison_bulk_delete_leads,
    bulk_update_lead_status as emailbison_bulk_update_lead_status,
    bulk_update_sender_email_daily_limits as emailbison_bulk_update_sender_email_daily_limits,
    bulk_update_sender_email_signatures as emailbison_bulk_update_sender_email_signatures,
    bulk_create_blacklisted_domains as emailbison_bulk_create_blacklisted_domains,
    bulk_create_blacklisted_emails as emailbison_bulk_create_blacklisted_emails,
    create_blacklisted_domain as emailbison_create_blacklisted_domain,
    create_blacklisted_email as emailbison_create_blacklisted_email,
    create_custom_variable as emailbison_create_custom_variable,
    create_tag as emailbison_create_tag,
    delete_blacklisted_domain as emailbison_delete_blacklisted_domain,
    delete_blacklisted_email as emailbison_delete_blacklisted_email,
    delete_webhook as emailbison_delete_webhook,
    delete_tag as emailbison_delete_tag,
    get_sample_webhook_payload as emailbison_get_sample_webhook_payload,
    get_campaign_events_stats as emailbison_get_campaign_events_stats,
    get_tag as emailbison_get_tag,
    get_webhook as emailbison_get_webhook,
    get_webhook_event_types as emailbison_get_webhook_event_types,
    get_workspace_account_details as emailbison_get_workspace_account_details,
    get_workspace_master_inbox_settings as emailbison_get_workspace_master_inbox_settings,
    get_workspace_stats as emailbison_get_workspace_stats,
    list_blacklisted_domains as emailbison_list_blacklisted_domains,
    list_blacklisted_emails as emailbison_list_blacklisted_emails,
    list_custom_variables as emailbison_list_custom_variables,
    list_tags as emailbison_list_tags,
    list_webhooks as emailbison_list_webhooks,
    remove_tags_from_campaigns as emailbison_remove_tags_from_campaigns,
    remove_tags_from_leads as emailbison_remove_tags_from_leads,
    remove_tags_from_sender_emails as emailbison_remove_tags_from_sender_emails,
    send_test_webhook_event as emailbison_send_test_webhook_event,
    update_workspace_master_inbox_settings as emailbison_update_workspace_master_inbox_settings,
    update_webhook as emailbison_update_webhook,
    create_webhook as emailbison_create_webhook,
)


router = APIRouter(prefix="/api/email-outreach", tags=["email-outreach"])


def _raise_provider_http_error(operation: str, exc: EmailBisonProviderError) -> None:
    raise HTTPException(
        status_code=provider_error_http_status(exc),
        detail=provider_error_detail(provider="emailbison", operation=operation, exc=exc),
    ) from exc


def _get_org_provider_config(org_id: str, provider_slug: str) -> dict[str, Any]:
    result = supabase.table("organizations").select("provider_configs").eq(
        "id", org_id
    ).is_("deleted_at", "null").execute()
    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    provider_configs = result.data[0].get("provider_configs") or {}
    provider_config = provider_configs.get(provider_slug) or {}
    api_key = provider_config.get("api_key")
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Missing org-level {provider_slug} API key",
        )
    return {"api_key": api_key, "instance_url": provider_config.get("instance_url")}


def _get_provider_slug(provider_id: str) -> str:
    provider = supabase.table("providers").select("id, slug").eq("id", provider_id).execute()
    if not provider.data:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Provider not configured")
    return provider.data[0]["slug"]


def _get_campaign_for_auth(auth: AuthContext, campaign_id: str) -> dict[str, Any]:
    query = supabase.table("company_campaigns").select(
        "id, org_id, company_id, provider_id, external_campaign_id"
    ).eq("id", campaign_id).eq("org_id", auth.org_id).is_("deleted_at", "null")
    if auth.company_id:
        query = query.eq("company_id", auth.company_id)
    result = query.execute()
    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")
    return result.data[0]


def _get_campaign_lead_for_auth(auth: AuthContext, campaign_id: str, lead_id: str) -> dict[str, Any]:
    _get_campaign_for_auth(auth, campaign_id)
    query = supabase.table("company_campaign_leads").select(
        "id, org_id, company_campaign_id, external_lead_id"
    ).eq("id", lead_id).eq("org_id", auth.org_id).eq("company_campaign_id", campaign_id).is_("deleted_at", "null")
    result = query.execute()
    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")
    return result.data[0]


def _get_inbox_for_auth(auth: AuthContext, inbox_id: str) -> dict[str, Any]:
    query = supabase.table("company_inboxes").select(
        "id, org_id, company_id, provider_id, external_account_id"
    ).eq("id", inbox_id).eq("org_id", auth.org_id).is_("deleted_at", "null")
    if auth.company_id:
        query = query.eq("company_id", auth.company_id)
    result = query.execute()
    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inbox not found")
    return result.data[0]


def _require_emailbison_provider(provider_id: str, context: str) -> None:
    if _get_provider_slug(provider_id) != "emailbison":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{context} unsupported for current provider",
        )


def _to_int(value: str, *, context: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{context} failed: non-numeric external identifier",
        )


def _get_inboxes_for_auth(auth: AuthContext, inbox_ids: list[str]) -> list[dict[str, Any]]:
    inboxes: list[dict[str, Any]] = []
    for inbox_id in inbox_ids:
        inboxes.append(_get_inbox_for_auth(auth, inbox_id))
    return inboxes


def _get_campaigns_for_auth(auth: AuthContext, campaign_ids: list[str]) -> list[dict[str, Any]]:
    campaigns: list[dict[str, Any]] = []
    for campaign_id in campaign_ids:
        campaigns.append(_get_campaign_for_auth(auth, campaign_id))
    return campaigns


@router.get("/webhooks")
async def list_webhooks(auth: AuthContext = Depends(get_current_auth)):
    creds = _get_org_provider_config(auth.org_id, "emailbison")
    try:
        rows = emailbison_list_webhooks(
            api_key=creds["api_key"],
            instance_url=creds.get("instance_url"),
        )
    except EmailBisonProviderError as exc:
        _raise_provider_http_error("webhooks_list", exc)
    return {"provider": "email_outreach", "webhooks": rows}


@router.post("/webhooks")
async def create_webhook(data: EmailOutreachWebhookCreateRequest, auth: AuthContext = Depends(get_current_auth)):
    creds = _get_org_provider_config(auth.org_id, "emailbison")
    try:
        row = emailbison_create_webhook(
            api_key=creds["api_key"],
            instance_url=creds.get("instance_url"),
            name=data.name,
            url=data.url,
            events=data.events,
        )
    except EmailBisonProviderError as exc:
        _raise_provider_http_error("webhooks_create", exc)
    return {"provider": "email_outreach", "webhook": row}


@router.get("/webhooks/{webhook_id}")
async def get_webhook(webhook_id: str, auth: AuthContext = Depends(get_current_auth)):
    creds = _get_org_provider_config(auth.org_id, "emailbison")
    try:
        row = emailbison_get_webhook(
            api_key=creds["api_key"],
            instance_url=creds.get("instance_url"),
            webhook_id=webhook_id,
        )
    except EmailBisonProviderError as exc:
        _raise_provider_http_error("webhooks_get", exc)
    return {"provider": "email_outreach", "webhook": row}


@router.put("/webhooks/{webhook_id}")
async def update_webhook(
    webhook_id: str,
    data: EmailOutreachWebhookUpdateRequest,
    auth: AuthContext = Depends(get_current_auth),
):
    creds = _get_org_provider_config(auth.org_id, "emailbison")
    try:
        row = emailbison_update_webhook(
            api_key=creds["api_key"],
            instance_url=creds.get("instance_url"),
            webhook_id=webhook_id,
            name=data.name,
            url=data.url,
            events=data.events,
        )
    except EmailBisonProviderError as exc:
        _raise_provider_http_error("webhooks_update", exc)
    return {"provider": "email_outreach", "webhook": row}


@router.delete("/webhooks/{webhook_id}")
async def delete_webhook(webhook_id: str, auth: AuthContext = Depends(get_current_auth)):
    creds = _get_org_provider_config(auth.org_id, "emailbison")
    try:
        result = emailbison_delete_webhook(
            api_key=creds["api_key"],
            instance_url=creds.get("instance_url"),
            webhook_id=webhook_id,
        )
    except EmailBisonProviderError as exc:
        _raise_provider_http_error("webhooks_delete", exc)
    return {"provider": "email_outreach", "result": result}


@router.get("/webhooks/event-types")
async def get_webhook_event_types(auth: AuthContext = Depends(get_current_auth)):
    creds = _get_org_provider_config(auth.org_id, "emailbison")
    try:
        rows = emailbison_get_webhook_event_types(
            api_key=creds["api_key"],
            instance_url=creds.get("instance_url"),
        )
    except EmailBisonProviderError as exc:
        _raise_provider_http_error("webhooks_event_types_get", exc)
    return {"provider": "email_outreach", "event_types": rows}


@router.post("/webhooks/sample-payload")
async def get_sample_webhook_payload(
    data: EmailOutreachWebhookSamplePayloadRequest,
    auth: AuthContext = Depends(get_current_auth),
):
    creds = _get_org_provider_config(auth.org_id, "emailbison")
    try:
        payload = emailbison_get_sample_webhook_payload(
            api_key=creds["api_key"],
            instance_url=creds.get("instance_url"),
            event_type=data.event_type,
        )
    except EmailBisonProviderError as exc:
        _raise_provider_http_error("webhooks_sample_payload_get", exc)
    return {"provider": "email_outreach", "payload": payload}


@router.post("/webhooks/test-event")
async def send_test_webhook_event(
    data: EmailOutreachWebhookTestEventRequest,
    auth: AuthContext = Depends(get_current_auth),
):
    creds = _get_org_provider_config(auth.org_id, "emailbison")
    try:
        result = emailbison_send_test_webhook_event(
            api_key=creds["api_key"],
            instance_url=creds.get("instance_url"),
            event_type=data.event_type,
            url=data.url,
        )
    except EmailBisonProviderError as exc:
        _raise_provider_http_error("webhooks_test_event_send", exc)
    return {"provider": "email_outreach", "result": result}


@router.delete("/campaigns/bulk")
async def bulk_delete_campaigns(
    data: EmailOutreachBulkCampaignDeleteRequest,
    auth: AuthContext = Depends(get_current_auth),
):
    campaigns = _get_campaigns_for_auth(auth, data.campaign_ids)
    _ = [_require_emailbison_provider(campaign["provider_id"], "Campaign bulk delete") for campaign in campaigns]
    external_campaign_ids = [_to_int(campaign["external_campaign_id"], context="Campaign bulk delete") for campaign in campaigns]
    creds = _get_org_provider_config(auth.org_id, "emailbison")
    try:
        result = emailbison_bulk_delete_campaigns(
            api_key=creds["api_key"],
            instance_url=creds.get("instance_url"),
            campaign_ids=external_campaign_ids,
        )
    except EmailBisonProviderError as exc:
        _raise_provider_http_error("campaigns_bulk_delete", exc)
    return {"provider": "email_outreach", "result": result}


@router.patch("/inboxes/bulk/signatures")
async def bulk_update_inbox_signatures(
    data: EmailOutreachBulkInboxSignatureUpdateRequest,
    auth: AuthContext = Depends(get_current_auth),
):
    inboxes = _get_inboxes_for_auth(auth, data.inbox_ids)
    _ = [_require_emailbison_provider(inbox["provider_id"], "Inbox signatures bulk update") for inbox in inboxes]
    sender_email_ids = [_to_int(inbox["external_account_id"], context="Inbox signatures bulk update") for inbox in inboxes]
    creds = _get_org_provider_config(auth.org_id, "emailbison")
    try:
        result = emailbison_bulk_update_sender_email_signatures(
            api_key=creds["api_key"],
            instance_url=creds.get("instance_url"),
            sender_email_ids=sender_email_ids,
            email_signature=data.email_signature,
        )
    except EmailBisonProviderError as exc:
        _raise_provider_http_error("inboxes_bulk_signatures_update", exc)
    return {"provider": "email_outreach", "result": result}


@router.patch("/inboxes/bulk/daily-limits")
async def bulk_update_inbox_daily_limits(
    data: EmailOutreachBulkInboxDailyLimitUpdateRequest,
    auth: AuthContext = Depends(get_current_auth),
):
    inboxes = _get_inboxes_for_auth(auth, data.inbox_ids)
    _ = [_require_emailbison_provider(inbox["provider_id"], "Inbox daily-limits bulk update") for inbox in inboxes]
    sender_email_ids = [_to_int(inbox["external_account_id"], context="Inbox daily-limits bulk update") for inbox in inboxes]
    creds = _get_org_provider_config(auth.org_id, "emailbison")
    try:
        result = emailbison_bulk_update_sender_email_daily_limits(
            api_key=creds["api_key"],
            instance_url=creds.get("instance_url"),
            sender_email_ids=sender_email_ids,
            daily_limit=data.daily_limit,
        )
    except EmailBisonProviderError as exc:
        _raise_provider_http_error("inboxes_bulk_daily_limits_update", exc)
    return {"provider": "email_outreach", "result": result}


@router.post("/inboxes/bulk/create")
async def bulk_create_inboxes(
    data: EmailOutreachBulkInboxesCreateRequest,
    auth: AuthContext = Depends(get_current_auth),
):
    creds = _get_org_provider_config(auth.org_id, "emailbison")
    try:
        rows = emailbison_bulk_create_sender_emails(
            api_key=creds["api_key"],
            instance_url=creds.get("instance_url"),
            payload=data.payload,
        )
    except EmailBisonProviderError as exc:
        _raise_provider_http_error("inboxes_bulk_create", exc)
    return {"provider": "email_outreach", "rows": rows}


@router.post("/leads/bulk/csv")
async def bulk_create_leads_csv(
    data: EmailOutreachBulkLeadsCsvCreateRequest,
    auth: AuthContext = Depends(get_current_auth),
):
    creds = _get_org_provider_config(auth.org_id, "emailbison")
    try:
        rows = emailbison_bulk_create_leads_csv(
            api_key=creds["api_key"],
            instance_url=creds.get("instance_url"),
            payload=data.payload,
        )
    except EmailBisonProviderError as exc:
        _raise_provider_http_error("leads_bulk_csv_create", exc)
    return {"provider": "email_outreach", "rows": rows}


@router.patch("/leads/bulk/status")
async def bulk_update_lead_status(
    data: EmailOutreachBulkLeadStatusUpdateRequest,
    auth: AuthContext = Depends(get_current_auth),
):
    campaign = _get_campaign_for_auth(auth, data.campaign_id)
    _require_emailbison_provider(campaign["provider_id"], "Lead status bulk update")
    leads = [_get_campaign_lead_for_auth(auth, data.campaign_id, lead_id) for lead_id in data.lead_ids]
    external_lead_ids = [_to_int(lead["external_lead_id"], context="Lead status bulk update") for lead in leads]
    creds = _get_org_provider_config(auth.org_id, "emailbison")
    try:
        result = emailbison_bulk_update_lead_status(
            api_key=creds["api_key"],
            instance_url=creds.get("instance_url"),
            lead_ids=external_lead_ids,
            status=data.status,
        )
    except EmailBisonProviderError as exc:
        _raise_provider_http_error("leads_bulk_status_update", exc)
    return {"provider": "email_outreach", "result": result}


@router.delete("/leads/bulk")
async def bulk_delete_leads(
    data: EmailOutreachBulkLeadDeleteRequest,
    auth: AuthContext = Depends(get_current_auth),
):
    campaign = _get_campaign_for_auth(auth, data.campaign_id)
    _require_emailbison_provider(campaign["provider_id"], "Lead bulk delete")
    leads = [_get_campaign_lead_for_auth(auth, data.campaign_id, lead_id) for lead_id in data.lead_ids]
    external_lead_ids = [_to_int(lead["external_lead_id"], context="Lead bulk delete") for lead in leads]
    creds = _get_org_provider_config(auth.org_id, "emailbison")
    try:
        result = emailbison_bulk_delete_leads(
            api_key=creds["api_key"],
            instance_url=creds.get("instance_url"),
            lead_ids=external_lead_ids,
        )
    except EmailBisonProviderError as exc:
        _raise_provider_http_error("leads_bulk_delete", exc)
    return {"provider": "email_outreach", "result": result}


@router.get("/workspace/account")
async def get_workspace_account(auth: AuthContext = Depends(get_current_auth)):
    creds = _get_org_provider_config(auth.org_id, "emailbison")
    try:
        account = emailbison_get_workspace_account_details(
            api_key=creds["api_key"],
            instance_url=creds.get("instance_url"),
        )
    except EmailBisonProviderError as exc:
        _raise_provider_http_error("workspace_account_get", exc)
    return {"provider": "email_outreach", "account": account}


@router.post("/workspace/stats")
async def get_workspace_stats(
    data: EmailOutreachWorkspaceStatsRequest,
    auth: AuthContext = Depends(get_current_auth),
):
    creds = _get_org_provider_config(auth.org_id, "emailbison")
    try:
        stats = emailbison_get_workspace_stats(
            api_key=creds["api_key"],
            instance_url=creds.get("instance_url"),
            start_date=data.start_date,
            end_date=data.end_date,
        )
    except EmailBisonProviderError as exc:
        _raise_provider_http_error("workspace_stats_get", exc)
    return {"provider": "email_outreach", "stats": stats}


@router.get("/workspace/master-inbox-settings")
async def get_workspace_master_inbox_settings(auth: AuthContext = Depends(get_current_auth)):
    creds = _get_org_provider_config(auth.org_id, "emailbison")
    try:
        settings = emailbison_get_workspace_master_inbox_settings(
            api_key=creds["api_key"],
            instance_url=creds.get("instance_url"),
        )
    except EmailBisonProviderError as exc:
        _raise_provider_http_error("workspace_master_inbox_settings_get", exc)
    return {"provider": "email_outreach", "settings": settings}


@router.patch("/workspace/master-inbox-settings")
async def update_workspace_master_inbox_settings(
    data: EmailOutreachWorkspaceMasterInboxSettingsUpdateRequest,
    auth: AuthContext = Depends(get_current_auth),
):
    updates = data.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No settings fields provided")
    creds = _get_org_provider_config(auth.org_id, "emailbison")
    try:
        settings = emailbison_update_workspace_master_inbox_settings(
            api_key=creds["api_key"],
            instance_url=creds.get("instance_url"),
            updates=updates,
        )
    except EmailBisonProviderError as exc:
        _raise_provider_http_error("workspace_master_inbox_settings_update", exc)
    return {"provider": "email_outreach", "settings": settings}


@router.post("/workspace/campaign-events/stats")
async def get_workspace_campaign_events_stats(
    data: EmailOutreachCampaignEventsStatsRequest,
    auth: AuthContext = Depends(get_current_auth),
):
    external_campaign_ids: list[int] | None = None
    external_sender_ids: list[int] | None = None

    if data.campaign_ids:
        campaigns = [_get_campaign_for_auth(auth, campaign_id) for campaign_id in data.campaign_ids]
        _ = [_require_emailbison_provider(campaign["provider_id"], "Campaign events stats") for campaign in campaigns]
        external_campaign_ids = [_to_int(campaign["external_campaign_id"], context="Campaign events stats") for campaign in campaigns]

    if data.inbox_ids:
        inboxes = _get_inboxes_for_auth(auth, data.inbox_ids)
        _ = [_require_emailbison_provider(inbox["provider_id"], "Campaign events stats") for inbox in inboxes]
        external_sender_ids = [_to_int(inbox["external_account_id"], context="Campaign events stats") for inbox in inboxes]

    creds = _get_org_provider_config(auth.org_id, "emailbison")
    try:
        stats = emailbison_get_campaign_events_stats(
            api_key=creds["api_key"],
            instance_url=creds.get("instance_url"),
            start_date=data.start_date,
            end_date=data.end_date,
            campaign_ids=external_campaign_ids,
            sender_email_ids=external_sender_ids,
        )
    except EmailBisonProviderError as exc:
        _raise_provider_http_error("workspace_campaign_events_stats_get", exc)
    return {"provider": "email_outreach", "stats": stats}


@router.get("/tags")
async def list_tags(auth: AuthContext = Depends(get_current_auth)):
    creds = _get_org_provider_config(auth.org_id, "emailbison")
    try:
        tags = emailbison_list_tags(api_key=creds["api_key"], instance_url=creds.get("instance_url"))
    except EmailBisonProviderError as exc:
        _raise_provider_http_error("tags_list", exc)
    return {"provider": "email_outreach", "tags": tags}


@router.post("/tags")
async def create_tag(data: EmailOutreachTagCreateRequest, auth: AuthContext = Depends(get_current_auth)):
    creds = _get_org_provider_config(auth.org_id, "emailbison")
    try:
        tag = emailbison_create_tag(
            api_key=creds["api_key"],
            instance_url=creds.get("instance_url"),
            name=data.name,
            default=data.default,
        )
    except EmailBisonProviderError as exc:
        _raise_provider_http_error("tags_create", exc)
    return {"provider": "email_outreach", "tag": tag}


@router.get("/tags/{tag_id}")
async def get_tag(tag_id: str, auth: AuthContext = Depends(get_current_auth)):
    creds = _get_org_provider_config(auth.org_id, "emailbison")
    try:
        tag = emailbison_get_tag(
            api_key=creds["api_key"],
            instance_url=creds.get("instance_url"),
            tag_id=tag_id,
        )
    except EmailBisonProviderError as exc:
        _raise_provider_http_error("tags_get", exc)
    return {"provider": "email_outreach", "tag": tag}


@router.delete("/tags/{tag_id}")
async def delete_tag(tag_id: str, auth: AuthContext = Depends(get_current_auth)):
    creds = _get_org_provider_config(auth.org_id, "emailbison")
    try:
        result = emailbison_delete_tag(
            api_key=creds["api_key"],
            instance_url=creds.get("instance_url"),
            tag_id=tag_id,
        )
    except EmailBisonProviderError as exc:
        _raise_provider_http_error("tags_delete", exc)
    return {"provider": "email_outreach", "result": result}


@router.post("/tags/attach/campaigns")
async def attach_tags_to_campaigns(data: EmailOutreachTagAttachCampaignsRequest, auth: AuthContext = Depends(get_current_auth)):
    campaigns = [_get_campaign_for_auth(auth, campaign_id) for campaign_id in data.campaign_ids]
    _ = [_require_emailbison_provider(campaign["provider_id"], "Campaign tag attach") for campaign in campaigns]
    external_campaign_ids = [_to_int(campaign["external_campaign_id"], context="Campaign tag attach") for campaign in campaigns]
    creds = _get_org_provider_config(auth.org_id, "emailbison")
    try:
        result = emailbison_attach_tags_to_campaigns(
            api_key=creds["api_key"],
            instance_url=creds.get("instance_url"),
            tag_ids=data.tag_ids,
            campaign_ids=external_campaign_ids,
            skip_webhooks=data.skip_webhooks,
        )
    except EmailBisonProviderError as exc:
        _raise_provider_http_error("tags_attach_campaigns", exc)
    return {"provider": "email_outreach", "result": result}


@router.post("/tags/remove/campaigns")
async def remove_tags_from_campaigns(data: EmailOutreachTagAttachCampaignsRequest, auth: AuthContext = Depends(get_current_auth)):
    campaigns = [_get_campaign_for_auth(auth, campaign_id) for campaign_id in data.campaign_ids]
    _ = [_require_emailbison_provider(campaign["provider_id"], "Campaign tag remove") for campaign in campaigns]
    external_campaign_ids = [_to_int(campaign["external_campaign_id"], context="Campaign tag remove") for campaign in campaigns]
    creds = _get_org_provider_config(auth.org_id, "emailbison")
    try:
        result = emailbison_remove_tags_from_campaigns(
            api_key=creds["api_key"],
            instance_url=creds.get("instance_url"),
            tag_ids=data.tag_ids,
            campaign_ids=external_campaign_ids,
            skip_webhooks=data.skip_webhooks,
        )
    except EmailBisonProviderError as exc:
        _raise_provider_http_error("tags_remove_campaigns", exc)
    return {"provider": "email_outreach", "result": result}


@router.post("/tags/attach/leads")
async def attach_tags_to_leads(data: EmailOutreachTagAttachLeadsRequest, auth: AuthContext = Depends(get_current_auth)):
    campaign = _get_campaign_for_auth(auth, data.campaign_id)
    _require_emailbison_provider(campaign["provider_id"], "Lead tag attach")
    leads = [_get_campaign_lead_for_auth(auth, data.campaign_id, lead_id) for lead_id in data.lead_ids]
    external_lead_ids = [_to_int(lead["external_lead_id"], context="Lead tag attach") for lead in leads]
    creds = _get_org_provider_config(auth.org_id, "emailbison")
    try:
        result = emailbison_attach_tags_to_leads(
            api_key=creds["api_key"],
            instance_url=creds.get("instance_url"),
            tag_ids=data.tag_ids,
            lead_ids=external_lead_ids,
            skip_webhooks=data.skip_webhooks,
        )
    except EmailBisonProviderError as exc:
        _raise_provider_http_error("tags_attach_leads", exc)
    return {"provider": "email_outreach", "result": result}


@router.post("/tags/remove/leads")
async def remove_tags_from_leads(data: EmailOutreachTagAttachLeadsRequest, auth: AuthContext = Depends(get_current_auth)):
    campaign = _get_campaign_for_auth(auth, data.campaign_id)
    _require_emailbison_provider(campaign["provider_id"], "Lead tag remove")
    leads = [_get_campaign_lead_for_auth(auth, data.campaign_id, lead_id) for lead_id in data.lead_ids]
    external_lead_ids = [_to_int(lead["external_lead_id"], context="Lead tag remove") for lead in leads]
    creds = _get_org_provider_config(auth.org_id, "emailbison")
    try:
        result = emailbison_remove_tags_from_leads(
            api_key=creds["api_key"],
            instance_url=creds.get("instance_url"),
            tag_ids=data.tag_ids,
            lead_ids=external_lead_ids,
            skip_webhooks=data.skip_webhooks,
        )
    except EmailBisonProviderError as exc:
        _raise_provider_http_error("tags_remove_leads", exc)
    return {"provider": "email_outreach", "result": result}


@router.post("/tags/attach/inboxes")
async def attach_tags_to_inboxes(data: EmailOutreachTagAttachInboxesRequest, auth: AuthContext = Depends(get_current_auth)):
    inboxes = [_get_inbox_for_auth(auth, inbox_id) for inbox_id in data.inbox_ids]
    _ = [_require_emailbison_provider(inbox["provider_id"], "Inbox tag attach") for inbox in inboxes]
    external_sender_ids = [_to_int(inbox["external_account_id"], context="Inbox tag attach") for inbox in inboxes]
    creds = _get_org_provider_config(auth.org_id, "emailbison")
    try:
        result = emailbison_attach_tags_to_sender_emails(
            api_key=creds["api_key"],
            instance_url=creds.get("instance_url"),
            tag_ids=data.tag_ids,
            sender_email_ids=external_sender_ids,
            skip_webhooks=data.skip_webhooks,
        )
    except EmailBisonProviderError as exc:
        _raise_provider_http_error("tags_attach_inboxes", exc)
    return {"provider": "email_outreach", "result": result}


@router.post("/tags/remove/inboxes")
async def remove_tags_from_inboxes(data: EmailOutreachTagAttachInboxesRequest, auth: AuthContext = Depends(get_current_auth)):
    inboxes = [_get_inbox_for_auth(auth, inbox_id) for inbox_id in data.inbox_ids]
    _ = [_require_emailbison_provider(inbox["provider_id"], "Inbox tag remove") for inbox in inboxes]
    external_sender_ids = [_to_int(inbox["external_account_id"], context="Inbox tag remove") for inbox in inboxes]
    creds = _get_org_provider_config(auth.org_id, "emailbison")
    try:
        result = emailbison_remove_tags_from_sender_emails(
            api_key=creds["api_key"],
            instance_url=creds.get("instance_url"),
            tag_ids=data.tag_ids,
            sender_email_ids=external_sender_ids,
            skip_webhooks=data.skip_webhooks,
        )
    except EmailBisonProviderError as exc:
        _raise_provider_http_error("tags_remove_inboxes", exc)
    return {"provider": "email_outreach", "result": result}


@router.get("/custom-variables")
async def list_custom_variables(auth: AuthContext = Depends(get_current_auth)):
    creds = _get_org_provider_config(auth.org_id, "emailbison")
    try:
        variables = emailbison_list_custom_variables(api_key=creds["api_key"], instance_url=creds.get("instance_url"))
    except EmailBisonProviderError as exc:
        _raise_provider_http_error("custom_variables_list", exc)
    return {"provider": "email_outreach", "custom_variables": variables}


@router.post("/custom-variables")
async def create_custom_variable(data: EmailOutreachCustomVariableCreateRequest, auth: AuthContext = Depends(get_current_auth)):
    creds = _get_org_provider_config(auth.org_id, "emailbison")
    try:
        variable = emailbison_create_custom_variable(
            api_key=creds["api_key"],
            instance_url=creds.get("instance_url"),
            name=data.name,
        )
    except EmailBisonProviderError as exc:
        _raise_provider_http_error("custom_variables_create", exc)
    return {"provider": "email_outreach", "custom_variable": variable}


@router.get("/blocklist/emails")
async def list_blocklisted_emails(auth: AuthContext = Depends(get_current_auth)):
    creds = _get_org_provider_config(auth.org_id, "emailbison")
    try:
        rows = emailbison_list_blacklisted_emails(api_key=creds["api_key"], instance_url=creds.get("instance_url"))
    except EmailBisonProviderError as exc:
        _raise_provider_http_error("blocklist_emails_list", exc)
    return {"provider": "email_outreach", "emails": rows}


@router.post("/blocklist/emails")
async def create_blocklisted_email(data: EmailOutreachBlocklistEmailCreateRequest, auth: AuthContext = Depends(get_current_auth)):
    creds = _get_org_provider_config(auth.org_id, "emailbison")
    try:
        row = emailbison_create_blacklisted_email(
            api_key=creds["api_key"],
            instance_url=creds.get("instance_url"),
            email=data.email,
        )
    except EmailBisonProviderError as exc:
        _raise_provider_http_error("blocklist_emails_create", exc)
    return {"provider": "email_outreach", "email": row}


@router.post("/blocklist/emails/bulk")
async def bulk_create_blocklisted_emails(
    data: EmailOutreachBlocklistEmailsBulkCreateRequest,
    auth: AuthContext = Depends(get_current_auth),
):
    creds = _get_org_provider_config(auth.org_id, "emailbison")
    try:
        rows = emailbison_bulk_create_blacklisted_emails(
            api_key=creds["api_key"],
            instance_url=creds.get("instance_url"),
            emails=data.emails,
        )
    except EmailBisonProviderError as exc:
        _raise_provider_http_error("blocklist_emails_bulk_create", exc)
    return {"provider": "email_outreach", "emails": rows}


@router.delete("/blocklist/emails/{blacklisted_email_id}")
async def delete_blocklisted_email(blacklisted_email_id: str, auth: AuthContext = Depends(get_current_auth)):
    creds = _get_org_provider_config(auth.org_id, "emailbison")
    try:
        result = emailbison_delete_blacklisted_email(
            api_key=creds["api_key"],
            instance_url=creds.get("instance_url"),
            blacklisted_email_id=blacklisted_email_id,
        )
    except EmailBisonProviderError as exc:
        _raise_provider_http_error("blocklist_emails_delete", exc)
    return {"provider": "email_outreach", "result": result}


@router.get("/blocklist/domains")
async def list_blocklisted_domains(auth: AuthContext = Depends(get_current_auth)):
    creds = _get_org_provider_config(auth.org_id, "emailbison")
    try:
        rows = emailbison_list_blacklisted_domains(api_key=creds["api_key"], instance_url=creds.get("instance_url"))
    except EmailBisonProviderError as exc:
        _raise_provider_http_error("blocklist_domains_list", exc)
    return {"provider": "email_outreach", "domains": rows}


@router.post("/blocklist/domains")
async def create_blocklisted_domain(data: EmailOutreachBlocklistDomainCreateRequest, auth: AuthContext = Depends(get_current_auth)):
    creds = _get_org_provider_config(auth.org_id, "emailbison")
    try:
        row = emailbison_create_blacklisted_domain(
            api_key=creds["api_key"],
            instance_url=creds.get("instance_url"),
            domain=data.domain,
        )
    except EmailBisonProviderError as exc:
        _raise_provider_http_error("blocklist_domains_create", exc)
    return {"provider": "email_outreach", "domain": row}


@router.post("/blocklist/domains/bulk")
async def bulk_create_blocklisted_domains(
    data: EmailOutreachBlocklistDomainsBulkCreateRequest,
    auth: AuthContext = Depends(get_current_auth),
):
    creds = _get_org_provider_config(auth.org_id, "emailbison")
    try:
        rows = emailbison_bulk_create_blacklisted_domains(
            api_key=creds["api_key"],
            instance_url=creds.get("instance_url"),
            domains=data.domains,
        )
    except EmailBisonProviderError as exc:
        _raise_provider_http_error("blocklist_domains_bulk_create", exc)
    return {"provider": "email_outreach", "domains": rows}


@router.delete("/blocklist/domains/{blacklisted_domain_id}")
async def delete_blocklisted_domain(blacklisted_domain_id: str, auth: AuthContext = Depends(get_current_auth)):
    creds = _get_org_provider_config(auth.org_id, "emailbison")
    try:
        result = emailbison_delete_blacklisted_domain(
            api_key=creds["api_key"],
            instance_url=creds.get("instance_url"),
            blacklisted_domain_id=blacklisted_domain_id,
        )
    except EmailBisonProviderError as exc:
        _raise_provider_http_error("blocklist_domains_delete", exc)
    return {"provider": "email_outreach", "result": result}
