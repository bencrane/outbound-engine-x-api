from __future__ import annotations

import hmac
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from src.auth import SuperAdminContext, get_current_super_admin
from src.config import settings
from src.db import supabase
from src.domain.normalization import (
    normalize_campaign_status,
    normalize_lead_status,
    normalize_message_direction,
)
from src.models.reconciliation import (
    ReconciliationProviderStats,
    ReconciliationRunRequest,
    ReconciliationRunResponse,
)
from src.observability import incr_metric, log_event, persist_metrics_snapshot
from src.providers.heyreach.client import (
    HeyReachProviderError,
    get_campaign_lead_messages as heyreach_get_campaign_lead_messages,
    get_campaign_leads as heyreach_get_campaign_leads,
    list_campaigns as heyreach_list_campaigns,
)
from src.providers.smartlead.client import (
    SmartleadProviderError,
    get_campaign_lead_messages as smartlead_get_campaign_lead_messages,
    get_campaign_replies as smartlead_get_campaign_replies,
    get_campaign_leads as smartlead_get_campaign_leads,
    list_campaigns as smartlead_list_campaigns,
)


router = APIRouter(prefix="/api/internal/reconciliation", tags=["internal-reconciliation"])


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now_utc().isoformat()


def _get_org_provider_api_key(org_id: str, provider_slug: str) -> str | None:
    org = (
        supabase.table("organizations")
        .select("provider_configs")
        .eq("id", org_id)
        .is_("deleted_at", "null")
        .execute()
    )
    if not org.data:
        return None
    provider_configs = org.data[0].get("provider_configs") or {}
    provider_config = provider_configs.get(provider_slug) or {}
    return provider_config.get("api_key")


def _extract_campaign(provider_slug: str, campaign: dict[str, Any]) -> dict[str, Any] | None:
    external_id = campaign.get("id") or campaign.get("campaignId") or campaign.get("campaign_id")
    if external_id is None:
        return None
    return {
        "external_campaign_id": str(external_id),
        "name": campaign.get("name") or campaign.get("campaign_name") or f"{provider_slug}_campaign_{external_id}",
        "status": normalize_campaign_status(campaign.get("status")),
        "raw_payload": campaign,
        "client_id": campaign.get("client_id"),
    }


def _extract_lead(lead: dict[str, Any]) -> dict[str, Any] | None:
    external_id = lead.get("id") or lead.get("lead_id") or lead.get("leadId")
    if external_id is None:
        return None
    return {
        "external_lead_id": str(external_id),
        "email": lead.get("email"),
        "first_name": lead.get("first_name") or lead.get("firstName"),
        "last_name": lead.get("last_name") or lead.get("lastName"),
        "company_name": lead.get("company") or lead.get("company_name"),
        "title": lead.get("title") or lead.get("position"),
        "status": normalize_lead_status(lead.get("status")),
        "raw_payload": lead,
    }


def _extract_message(
    message: dict[str, Any],
    default_direction: str = "unknown",
    fallback_external_lead_id: str | None = None,
) -> dict[str, Any] | None:
    external_id = message.get("id") or message.get("email_stats_id") or message.get("message_id")
    if external_id is None:
        return None
    lead_id = message.get("lead_id") or message.get("leadId")
    external_lead_id = str(lead_id) if lead_id is not None else fallback_external_lead_id
    sequence_step_number = None
    for key in ("sequence_step_number", "sequenceStepNumber", "step_number", "stepNumber", "seq_number"):
        raw = message.get(key)
        if raw is None:
            continue
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if value >= 1:
            sequence_step_number = value
            break
    return {
        "external_message_id": str(external_id),
        "external_lead_id": external_lead_id,
        "direction": normalize_message_direction(message.get("direction") or default_direction),
        "sequence_step_number": sequence_step_number,
        "subject": message.get("subject"),
        "body": message.get("email_body") or message.get("body") or message.get("message"),
        "sent_at": message.get("sent_at") or message.get("created_at") or message.get("timestamp"),
        "raw_payload": message,
    }


def _is_missing_or_unsupported_endpoint(exc: Exception) -> bool:
    text = str(exc).lower()
    return "endpoint not found" in text or "http 405" in text


def _provider_error_category(exc: Exception) -> str:
    return getattr(exc, "category", "unknown")


def _upsert_campaign_message(
    *,
    dry_run: bool,
    org_id: str,
    company_id: str,
    campaign_id: str,
    provider_id: str,
    local_lead_id: str | None,
    parsed: dict[str, Any],
) -> str:
    existing = (
        supabase.table("company_campaign_messages")
        .select(
            "id, external_lead_id, company_campaign_lead_id, direction, subject, body, sent_at"
        )
        .eq("org_id", org_id)
        .eq("company_campaign_id", campaign_id)
        .eq("provider_id", provider_id)
        .eq("external_message_id", parsed["external_message_id"])
        .is_("deleted_at", "null")
        .execute()
    ).data

    payload = {
        "org_id": org_id,
        "company_id": company_id,
        "company_campaign_id": campaign_id,
        "company_campaign_lead_id": local_lead_id,
        "provider_id": provider_id,
        "external_message_id": parsed["external_message_id"],
        "external_lead_id": parsed.get("external_lead_id"),
        "direction": parsed.get("direction") or "unknown",
        "sequence_step_number": parsed.get("sequence_step_number"),
        "subject": parsed.get("subject"),
        "body": parsed.get("body"),
        "sent_at": parsed.get("sent_at"),
        "raw_payload": parsed.get("raw_payload"),
        "updated_at": _now_iso(),
    }

    if existing:
        row = existing[0]
        changed = any(
            row.get(key) != payload.get(key)
            for key in [
                "external_lead_id",
                "company_campaign_lead_id",
                "direction",
                "sequence_step_number",
                "subject",
                "body",
                "sent_at",
            ]
        )
        if not changed:
            return "unchanged"
        if not dry_run:
            (
                supabase.table("company_campaign_messages")
                .update(payload)
                .eq("id", row["id"])
                .eq("org_id", org_id)
                .execute()
            )
        return "updated"

    if not dry_run:
        supabase.table("company_campaign_messages").insert(payload).execute()
    return "created"


def _update_campaign_message_sync_state(
    *,
    dry_run: bool,
    org_id: str,
    campaign_id: str,
    status_value: str,
    error_text: str | None,
) -> None:
    if dry_run:
        return
    (
        supabase.table("company_campaigns")
        .update(
            {
                "message_sync_status": status_value,
                "last_message_sync_at": _now_iso(),
                "last_message_sync_error": error_text,
                "updated_at": _now_iso(),
            }
        )
        .eq("id", campaign_id)
        .eq("org_id", org_id)
        .execute()
    )


@router.post("/campaigns-leads", response_model=ReconciliationRunResponse)
async def reconcile_campaigns_and_leads(
    data: ReconciliationRunRequest,
    request: Request,
    _ctx: SuperAdminContext = Depends(get_current_super_admin),
):
    request_id = getattr(request.state, "request_id", None)
    return _run_reconciliation(data, request_id=request_id)


def _run_reconciliation(data: ReconciliationRunRequest, request_id: str | None = None) -> ReconciliationRunResponse:
    started_at = _now_utc()
    provider_slugs = [data.provider_slug] if data.provider_slug else ["smartlead", "heyreach"]
    provider_stats: list[ReconciliationProviderStats] = []
    incr_metric("reconciliation.runs.started")
    log_event(
        "reconciliation_started",
        request_id=request_id,
        dry_run=data.dry_run,
        provider_slugs=provider_slugs,
        org_id=data.org_id,
        company_id=data.company_id,
        campaign_limit=data.campaign_limit,
        lead_limit=data.lead_limit,
        sync_messages=data.sync_messages,
        message_limit=data.message_limit,
    )

    providers = supabase.table("providers").select("id, slug").execute().data or []
    provider_id_by_slug = {row["slug"]: row["id"] for row in providers}

    for provider_slug in provider_slugs:
        if provider_slug not in provider_id_by_slug:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Provider not configured: {provider_slug}",
            )
        provider_id = provider_id_by_slug[provider_slug]
        stats = ReconciliationProviderStats(
            provider_slug=provider_slug,
            companies_scanned=0,
            campaigns_scanned=0,
            campaigns_created=0,
            campaigns_updated=0,
            leads_scanned=0,
            leads_created=0,
            leads_updated=0,
            messages_scanned=0,
            messages_created=0,
            messages_updated=0,
            errors=[],
        )

        ent_query = (
            supabase.table("company_entitlements")
            .select("id, org_id, company_id, provider_config")
            .eq("provider_id", provider_id)
        )
        if data.org_id:
            ent_query = ent_query.eq("org_id", data.org_id)
        if data.company_id:
            ent_query = ent_query.eq("company_id", data.company_id)
        entitlements = ent_query.execute().data or []

        for entitlement in entitlements:
            stats.companies_scanned += 1
            org_id = entitlement["org_id"]
            company_id = entitlement["company_id"]
            provider_config = entitlement.get("provider_config") or {}
            api_key = _get_org_provider_api_key(org_id, provider_slug)
            if not api_key:
                stats.errors.append(f"{provider_slug}:{org_id}:{company_id}: missing org api key")
                incr_metric("reconciliation.provider_errors", provider_slug=provider_slug, error_type="missing_api_key")
                continue

            try:
                if provider_slug == "smartlead":
                    campaigns = smartlead_list_campaigns(api_key=api_key, limit=data.campaign_limit, offset=0)
                    smartlead_client_id = provider_config.get("smartlead_client_id")
                    if smartlead_client_id is not None:
                        campaigns = [
                            row
                            for row in campaigns
                            if row.get("client_id") is None or str(row.get("client_id")) == str(smartlead_client_id)
                        ]
                else:
                    campaigns = heyreach_list_campaigns(api_key=api_key)
                    campaigns = campaigns[: data.campaign_limit]
            except (SmartleadProviderError, HeyReachProviderError) as exc:
                category = _provider_error_category(exc)
                stats.errors.append(f"{provider_slug}:{org_id}:{company_id}: campaign fetch failed [{category}]: {exc}")
                incr_metric(
                    "reconciliation.provider_errors",
                    provider_slug=provider_slug,
                    error_type="campaign_fetch",
                    category=category,
                )
                continue

            for provider_campaign in campaigns:
                parsed_campaign = _extract_campaign(provider_slug, provider_campaign)
                if not parsed_campaign:
                    continue
                stats.campaigns_scanned += 1

                existing_campaign = (
                    supabase.table("company_campaigns")
                    .select("id, status, name")
                    .eq("org_id", org_id)
                    .eq("company_id", company_id)
                    .eq("provider_id", provider_id)
                    .eq("external_campaign_id", parsed_campaign["external_campaign_id"])
                    .is_("deleted_at", "null")
                    .execute()
                ).data

                if existing_campaign:
                    local_campaign = existing_campaign[0]
                    if (
                        local_campaign.get("status") != parsed_campaign["status"]
                        or local_campaign.get("name") != parsed_campaign["name"]
                    ):
                        stats.campaigns_updated += 1
                        if not data.dry_run:
                            (
                                supabase.table("company_campaigns")
                                .update(
                                    {
                                        "status": parsed_campaign["status"],
                                        "name": parsed_campaign["name"],
                                        "raw_payload": parsed_campaign["raw_payload"],
                                        "updated_at": _now_iso(),
                                    }
                                )
                                .eq("id", local_campaign["id"])
                                .eq("org_id", org_id)
                                .execute()
                            )
                    campaign_id = local_campaign["id"]
                else:
                    stats.campaigns_created += 1
                    if data.dry_run:
                        campaign_id = f"dry-run-{provider_slug}-{parsed_campaign['external_campaign_id']}"
                    else:
                        created = (
                            supabase.table("company_campaigns")
                            .insert(
                                {
                                    "org_id": org_id,
                                    "company_id": company_id,
                                    "provider_id": provider_id,
                                    "external_campaign_id": parsed_campaign["external_campaign_id"],
                                    "name": parsed_campaign["name"],
                                    "status": parsed_campaign["status"],
                                    "raw_payload": parsed_campaign["raw_payload"],
                                    "updated_at": _now_iso(),
                                }
                            )
                            .execute()
                        )
                        campaign_id = created.data[0]["id"]

                try:
                    if provider_slug == "smartlead":
                        leads = smartlead_get_campaign_leads(
                            api_key=api_key,
                            campaign_id=parsed_campaign["external_campaign_id"],
                            limit=data.lead_limit,
                            offset=0,
                        )
                    else:
                        leads = heyreach_get_campaign_leads(
                            api_key=api_key,
                            campaign_id=parsed_campaign["external_campaign_id"],
                            page=1,
                            limit=min(data.lead_limit, 1000),
                        )
                except (SmartleadProviderError, HeyReachProviderError) as exc:
                    category = _provider_error_category(exc)
                    stats.errors.append(
                        f"{provider_slug}:{org_id}:{company_id}:{parsed_campaign['external_campaign_id']}: lead fetch failed [{category}]: {exc}"
                    )
                    incr_metric(
                        "reconciliation.provider_errors",
                        provider_slug=provider_slug,
                        error_type="lead_fetch",
                        category=category,
                    )
                    continue

                local_lead_id_by_external_id: dict[str, str] = {}
                for provider_lead in leads:
                    parsed_lead = _extract_lead(provider_lead)
                    if not parsed_lead:
                        continue
                    stats.leads_scanned += 1
                    existing_lead = (
                        supabase.table("company_campaign_leads")
                        .select("id, external_lead_id, status, email, first_name, last_name")
                        .eq("org_id", org_id)
                        .eq("company_campaign_id", campaign_id)
                        .eq("provider_id", provider_id)
                        .eq("external_lead_id", parsed_lead["external_lead_id"])
                        .is_("deleted_at", "null")
                        .execute()
                    ).data

                    if existing_lead:
                        local_lead = existing_lead[0]
                        local_lead_id_by_external_id[parsed_lead["external_lead_id"]] = local_lead["id"]
                        if (
                            local_lead.get("status") != parsed_lead["status"]
                            or local_lead.get("email") != parsed_lead["email"]
                            or local_lead.get("first_name") != parsed_lead["first_name"]
                            or local_lead.get("last_name") != parsed_lead["last_name"]
                        ):
                            stats.leads_updated += 1
                            if not data.dry_run:
                                (
                                    supabase.table("company_campaign_leads")
                                    .update(
                                        {
                                            "email": parsed_lead["email"],
                                            "first_name": parsed_lead["first_name"],
                                            "last_name": parsed_lead["last_name"],
                                            "company_name": parsed_lead["company_name"],
                                            "title": parsed_lead["title"],
                                            "status": parsed_lead["status"],
                                            "raw_payload": parsed_lead["raw_payload"],
                                            "updated_at": _now_iso(),
                                        }
                                    )
                                    .eq("id", local_lead["id"])
                                    .eq("org_id", org_id)
                                    .execute()
                                )
                    else:
                        stats.leads_created += 1
                        if data.dry_run:
                            local_lead_id_by_external_id[parsed_lead["external_lead_id"]] = (
                                f"dry-run-{campaign_id}-{parsed_lead['external_lead_id']}"
                            )
                        else:
                            created_lead = (
                                supabase.table("company_campaign_leads")
                                .insert(
                                    {
                                        "org_id": org_id,
                                        "company_id": company_id,
                                        "company_campaign_id": campaign_id,
                                        "provider_id": provider_id,
                                        "external_lead_id": parsed_lead["external_lead_id"],
                                        "email": parsed_lead["email"],
                                        "first_name": parsed_lead["first_name"],
                                        "last_name": parsed_lead["last_name"],
                                        "company_name": parsed_lead["company_name"],
                                        "title": parsed_lead["title"],
                                        "status": parsed_lead["status"],
                                        "raw_payload": parsed_lead["raw_payload"],
                                        "updated_at": _now_iso(),
                                    }
                                )
                                .execute()
                            )
                            if created_lead.data:
                                local_lead_id_by_external_id[parsed_lead["external_lead_id"]] = created_lead.data[0]["id"]

                campaign_message_sync_status = "skipped_disabled"
                campaign_message_sync_error: str | None = None
                if data.sync_messages and provider_slug == "smartlead":
                    campaign_message_sync_status = "success"
                    seen_message_ids: set[str] = set()
                    message_budget = data.message_limit

                    def _consume_messages(
                        raw_messages: list[dict[str, Any]],
                        *,
                        default_direction: str,
                        fallback_external_lead_id: str | None = None,
                    ) -> None:
                        nonlocal message_budget
                        for raw_message in raw_messages:
                            if message_budget <= 0:
                                return
                            parsed_message = _extract_message(
                                raw_message,
                                default_direction=default_direction,
                                fallback_external_lead_id=fallback_external_lead_id,
                            )
                            if not parsed_message:
                                continue
                            message_id = parsed_message["external_message_id"]
                            if message_id in seen_message_ids:
                                continue
                            seen_message_ids.add(message_id)
                            message_budget -= 1
                            stats.messages_scanned += 1
                            message_result = _upsert_campaign_message(
                                dry_run=data.dry_run,
                                org_id=org_id,
                                company_id=company_id,
                                campaign_id=campaign_id,
                                provider_id=provider_id,
                                local_lead_id=local_lead_id_by_external_id.get(
                                    parsed_message.get("external_lead_id") or ""
                                ),
                                parsed=parsed_message,
                            )
                            if message_result == "created":
                                stats.messages_created += 1
                            elif message_result == "updated":
                                stats.messages_updated += 1

                    try:
                        replies = smartlead_get_campaign_replies(
                            api_key=api_key,
                            campaign_id=parsed_campaign["external_campaign_id"],
                        )
                        _consume_messages(replies, default_direction="inbound")
                    except SmartleadProviderError as exc:
                        category = _provider_error_category(exc)
                        campaign_message_sync_status = "partial_error"
                        if not campaign_message_sync_error:
                            campaign_message_sync_error = (
                                f"replies fetch failed [{category}]: {exc}"
                            )
                        stats.errors.append(
                            f"{provider_slug}:{org_id}:{company_id}:{parsed_campaign['external_campaign_id']}: replies fetch failed [{category}]: {exc}"
                        )
                        incr_metric(
                            "reconciliation.provider_errors",
                            provider_slug=provider_slug,
                            error_type="replies_fetch",
                            category=category,
                        )

                    if message_budget > 0:
                        for external_lead_id in list(local_lead_id_by_external_id.keys()):
                            if message_budget <= 0:
                                break
                            try:
                                lead_messages = smartlead_get_campaign_lead_messages(
                                    api_key=api_key,
                                    campaign_id=parsed_campaign["external_campaign_id"],
                                    lead_id=external_lead_id,
                                )
                            except SmartleadProviderError as exc:
                                category = _provider_error_category(exc)
                                campaign_message_sync_status = "partial_error"
                                if not campaign_message_sync_error:
                                    campaign_message_sync_error = (
                                        f"lead messages fetch failed [{category}]: {exc}"
                                    )
                                stats.errors.append(
                                    f"{provider_slug}:{org_id}:{company_id}:{parsed_campaign['external_campaign_id']}:{external_lead_id}: lead messages fetch failed [{category}]: {exc}"
                                )
                                incr_metric(
                                    "reconciliation.provider_errors",
                                    provider_slug=provider_slug,
                                    error_type="lead_messages_fetch",
                                    category=category,
                                )
                                continue
                            _consume_messages(
                                lead_messages,
                                default_direction="unknown",
                                fallback_external_lead_id=external_lead_id,
                            )
                elif data.sync_messages and provider_slug == "heyreach":
                    mode = (settings.heyreach_message_sync_mode or "webhook_only").strip().lower()
                    if mode == "webhook_only":
                        campaign_message_sync_status = "skipped_webhook_only"
                        incr_metric("reconciliation.messages.skipped", provider_slug="heyreach", mode=mode)
                        log_event(
                            "reconciliation_message_sync_skipped",
                            request_id=request_id,
                            provider_slug="heyreach",
                            mode=mode,
                            reason="webhook_only_strategy",
                            campaign_id=campaign_id,
                            external_campaign_id=parsed_campaign["external_campaign_id"],
                        )
                    elif mode == "pull_best_effort":
                        campaign_message_sync_status = "success"
                        seen_message_ids: set[str] = set()
                        message_budget = data.message_limit
                        for external_lead_id in list(local_lead_id_by_external_id.keys()):
                            if message_budget <= 0:
                                break
                            try:
                                lead_messages = heyreach_get_campaign_lead_messages(
                                    api_key=api_key,
                                    lead_id=external_lead_id,
                                    page=1,
                                    limit=min(message_budget, 500),
                                )
                            except HeyReachProviderError as exc:
                                if _is_missing_or_unsupported_endpoint(exc):
                                    incr_metric(
                                        "reconciliation.messages.skipped",
                                        provider_slug="heyreach",
                                        mode=mode,
                                        reason="endpoint_unavailable",
                                    )
                                    continue
                                category = _provider_error_category(exc)
                                campaign_message_sync_status = "partial_error"
                                if not campaign_message_sync_error:
                                    campaign_message_sync_error = (
                                        f"heyreach lead messages fetch failed [{category}]: {exc}"
                                    )
                                stats.errors.append(
                                    f"{provider_slug}:{org_id}:{company_id}:{parsed_campaign['external_campaign_id']}:{external_lead_id}: heyreach lead messages fetch failed [{category}]: {exc}"
                                )
                                incr_metric(
                                    "reconciliation.provider_errors",
                                    provider_slug=provider_slug,
                                    error_type="lead_messages_fetch",
                                    category=category,
                                )
                                continue

                            for raw_message in lead_messages:
                                if message_budget <= 0:
                                    break
                                parsed_message = _extract_message(
                                    raw_message,
                                    default_direction="unknown",
                                    fallback_external_lead_id=external_lead_id,
                                )
                                if not parsed_message:
                                    continue
                                message_id = parsed_message["external_message_id"]
                                if message_id in seen_message_ids:
                                    continue
                                seen_message_ids.add(message_id)
                                message_budget -= 1
                                stats.messages_scanned += 1
                                message_result = _upsert_campaign_message(
                                    dry_run=data.dry_run,
                                    org_id=org_id,
                                    company_id=company_id,
                                    campaign_id=campaign_id,
                                    provider_id=provider_id,
                                    local_lead_id=local_lead_id_by_external_id.get(
                                        parsed_message.get("external_lead_id") or ""
                                    ),
                                    parsed=parsed_message,
                                )
                                if message_result == "created":
                                    stats.messages_created += 1
                                elif message_result == "updated":
                                    stats.messages_updated += 1
                    else:
                        campaign_message_sync_status = "error"
                        campaign_message_sync_error = (
                            f"invalid heyreach_message_sync_mode={settings.heyreach_message_sync_mode}"
                        )
                        stats.errors.append(
                            f"{provider_slug}:{org_id}:{company_id}: invalid heyreach_message_sync_mode={settings.heyreach_message_sync_mode}"
                        )
                        incr_metric("reconciliation.provider_errors", provider_slug=provider_slug, error_type="config")
                _update_campaign_message_sync_state(
                    dry_run=data.dry_run,
                    org_id=org_id,
                    campaign_id=campaign_id,
                    status_value=campaign_message_sync_status,
                    error_text=campaign_message_sync_error,
                )

        provider_stats.append(stats)
        incr_metric("reconciliation.providers.completed", provider_slug=provider_slug)
        log_event(
            "reconciliation_provider_completed",
            request_id=request_id,
            provider_slug=provider_slug,
            companies_scanned=stats.companies_scanned,
            campaigns_scanned=stats.campaigns_scanned,
            campaigns_created=stats.campaigns_created,
            campaigns_updated=stats.campaigns_updated,
            leads_scanned=stats.leads_scanned,
            leads_created=stats.leads_created,
            leads_updated=stats.leads_updated,
            messages_scanned=stats.messages_scanned,
            messages_created=stats.messages_created,
            messages_updated=stats.messages_updated,
            error_count=len(stats.errors),
        )

    response = ReconciliationRunResponse(
        dry_run=data.dry_run,
        started_at=started_at,
        finished_at=_now_utc(),
        providers=provider_stats,
    )
    incr_metric("reconciliation.runs.completed")
    log_event(
        "reconciliation_completed",
        request_id=request_id,
        provider_count=len(provider_stats),
        total_errors=sum(len(s.errors) for s in provider_stats),
        dry_run=data.dry_run,
    )
    persist_metrics_snapshot(
        supabase_client=supabase,
        source="reconciliation",
        request_id=request_id,
        reset_after_persist=False,
        export_url=settings.observability_export_url,
        export_bearer_token=settings.observability_export_bearer_token,
        export_timeout_seconds=settings.observability_export_timeout_seconds,
    )
    return response


@router.post("/run-scheduled", response_model=ReconciliationRunResponse)
async def run_reconciliation_scheduled(
    data: ReconciliationRunRequest,
    request: Request,
    x_internal_scheduler_secret: str | None = Header(default=None),
):
    request_id = getattr(request.state, "request_id", None)
    configured_secret = settings.internal_scheduler_secret
    if not configured_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="internal scheduler secret is not configured",
        )
    if not x_internal_scheduler_secret or not hmac.compare_digest(
        x_internal_scheduler_secret,
        configured_secret,
    ):
        incr_metric("reconciliation.scheduled.auth_failed")
        log_event("reconciliation_scheduled_auth_failed", request_id=request_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid scheduler secret",
        )
    incr_metric("reconciliation.scheduled.auth_succeeded")
    return _run_reconciliation(data, request_id=request_id)
