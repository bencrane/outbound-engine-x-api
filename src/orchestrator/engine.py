from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from src.config import settings
from src.db import supabase
from src.observability import incr_metric, log_event
from src.orchestrator.conditions import should_skip_step
from src.orchestrator.step_executor import execute_step


@dataclass
class OrchestratorTickResult:
    leads_processed: int = 0
    steps_executed: int = 0
    steps_succeeded: int = 0
    steps_retried: int = 0
    steps_failed: int = 0
    leads_completed: int = 0
    dry_run: bool = False
    errors: list[str] = field(default_factory=list)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _to_iso(value: datetime) -> str:
    return value.isoformat()


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _get_campaign(company_campaign_id: str) -> dict[str, Any]:
    campaign_rows = (
        supabase.table("company_campaigns")
        .select("id, org_id, company_id")
        .eq("id", company_campaign_id)
        .is_("deleted_at", "null")
        .execute()
        .data
        or []
    )
    if not campaign_rows or not campaign_rows[0].get("org_id"):
        raise ValueError(f"campaign not found for progress row campaign_id={company_campaign_id}")
    return campaign_rows[0]


def _get_lead_provider_id_map(org_id: str, company_campaign_lead_id: str) -> dict[str, str]:
    mappings = (
        supabase.table("campaign_lead_provider_ids")
        .select("provider_id, external_id")
        .eq("org_id", org_id)
        .eq("company_campaign_lead_id", company_campaign_lead_id)
        .execute()
        .data
        or []
    )
    provider_ids = {str(row.get("provider_id")) for row in mappings if row.get("provider_id")}
    provider_slug_by_id: dict[str, str] = {}
    if provider_ids:
        providers = supabase.table("providers").select("id, slug").execute().data or []
        provider_slug_by_id = {
            str(row.get("id")): str(row.get("slug"))
            for row in providers
            if row.get("id") and row.get("slug")
        }
    result: dict[str, str] = {}
    for row in mappings:
        provider_id = row.get("provider_id")
        external_id = row.get("external_id")
        if not provider_id or external_id is None:
            continue
        slug = provider_slug_by_id.get(str(provider_id))
        if slug:
            result[slug] = str(external_id)
    return result


def _next_retry_ts(attempts: int) -> datetime:
    retry_minutes = min(
        attempts * settings.orchestrator_retry_base_minutes,
        settings.orchestrator_retry_max_minutes,
    )
    return _now_utc() + timedelta(minutes=retry_minutes)


def _write_campaign_event(
    *,
    campaign: dict[str, Any],
    progress: dict[str, Any],
    step: dict[str, Any],
    event_type: str,
    provider_slug: str | None,
    payload: dict[str, Any] | None,
) -> None:
    try:
        supabase.table("campaign_events").insert(
            {
                "org_id": campaign["org_id"],
                "company_id": campaign.get("company_id"),
                "company_campaign_id": campaign["id"],
                "company_campaign_lead_id": progress["company_campaign_lead_id"],
                "event_type": event_type,
                "channel": step.get("channel"),
                "provider_slug": provider_slug,
                "step_order": step.get("step_order"),
                "payload": payload,
            }
        ).execute()
    except Exception as exc:
        log_event(
            "orchestrator_campaign_event_write_failed",
            campaign_id=campaign.get("id"),
            lead_id=progress.get("company_campaign_lead_id"),
            step_order=step.get("step_order"),
            event_type=event_type,
            error=str(exc),
        )


def _advance_progress_to_next_or_complete(
    *,
    progress_id: str,
    org_id: str,
    campaign_id: str,
    current_step_order: int,
    current_step_status: str,
) -> bool:
    next_order = int(current_step_order or 0) + 1
    next_step = _get_next_step(org_id, campaign_id, next_order)
    if next_step:
        delay_days = int(next_step.get("delay_days") or 0)
        next_execute_at = _now_utc() + timedelta(days=delay_days)
        (
            supabase.table("campaign_lead_progress")
            .update(
                {
                    "current_step_id": next_step["id"],
                    "current_step_order": next_order,
                    "step_status": "pending",
                    "next_execute_at": _to_iso(next_execute_at),
                    "attempts": 0,
                    "updated_at": _to_iso(_now_utc()),
                    "executed_at": _to_iso(_now_utc()) if current_step_status == "executed" else None,
                }
            )
            .eq("id", progress_id)
            .eq("org_id", org_id)
            .execute()
        )
        return False
    (
        supabase.table("campaign_lead_progress")
        .update(
            {
                "step_status": "completed",
                "completed_at": _to_iso(_now_utc()),
                "next_execute_at": None,
                "executed_at": _to_iso(_now_utc()) if current_step_status == "executed" else None,
                "updated_at": _to_iso(_now_utc()),
            }
        )
        .eq("id", progress_id)
        .eq("org_id", org_id)
        .execute()
    )
    return True


def _recover_stale_executing_rows() -> int:
    stale_before = _now_utc() - timedelta(minutes=settings.orchestrator_stale_lock_minutes)
    stale_rows = (
        supabase.table("campaign_lead_progress")
        .select("id, updated_at")
        .eq("step_status", "executing")
        .execute()
        .data
        or []
    )
    recovered = 0
    for row in stale_rows:
        updated_at = _parse_datetime(row.get("updated_at"))
        if updated_at is None or updated_at >= stale_before:
            continue
        (
            supabase.table("campaign_lead_progress")
            .update(
                {
                    "step_status": "pending",
                    "updated_at": _to_iso(_now_utc()),
                }
            )
            .eq("id", row["id"])
            .execute()
        )
        recovered += 1
    if recovered:
        incr_metric("orchestrator.stale_locks.recovered", value=recovered)
        log_event("orchestrator_stale_locks_recovered", recovered=recovered)
    return recovered


def _load_due_progress_rows(batch_size: int) -> list[dict[str, Any]]:
    return (
        supabase.table("campaign_lead_progress")
        .select("*")
        .eq("step_status", "pending")
        .lte("next_execute_at", _to_iso(_now_utc()))
        .order("next_execute_at")
        .limit(batch_size)
        .execute()
        .data
        or []
    )


def _get_next_step(org_id: str, company_campaign_id: str, next_order: int) -> dict[str, Any] | None:
    rows = (
        supabase.table("campaign_sequence_steps")
        .select("*")
        .eq("org_id", org_id)
        .eq("company_campaign_id", company_campaign_id)
        .eq("step_order", next_order)
        .is_("deleted_at", "null")
        .execute()
        .data
        or []
    )
    return rows[0] if rows else None


def _upsert_lead_provider_external_id(
    *,
    org_id: str,
    company_campaign_lead_id: str,
    provider_id: str,
    external_id: str,
) -> None:
    existing = (
        supabase.table("campaign_lead_provider_ids")
        .select("id")
        .eq("org_id", org_id)
        .eq("company_campaign_lead_id", company_campaign_lead_id)
        .eq("provider_id", provider_id)
        .execute()
        .data
        or []
    )
    payload = {
        "org_id": org_id,
        "company_campaign_lead_id": company_campaign_lead_id,
        "provider_id": provider_id,
        "external_id": external_id,
        "updated_at": _to_iso(_now_utc()),
    }
    if existing:
        (
            supabase.table("campaign_lead_provider_ids")
            .update(payload)
            .eq("id", existing[0]["id"])
            .eq("org_id", org_id)
            .execute()
        )
        return
    payload["created_at"] = _to_iso(_now_utc())
    supabase.table("campaign_lead_provider_ids").insert(payload).execute()


def _merge_action_config(step_config: dict[str, Any], lead_override: dict[str, Any] | None) -> dict[str, Any]:
    if not lead_override:
        return step_config
    merged = {**step_config}
    merged.update(lead_override)
    return merged


def run_orchestrator_tick(
    *,
    batch_size: int = 50,
    dry_run: bool = False,
) -> OrchestratorTickResult:
    result = OrchestratorTickResult(dry_run=dry_run)
    if batch_size <= 0:
        return result

    _recover_stale_executing_rows()
    due_rows = _load_due_progress_rows(batch_size=batch_size)
    now = _now_utc()

    for progress in due_rows:
        progress_id = str(progress.get("id") or "")
        if not progress_id:
            result.errors.append("progress row missing id")
            continue

        try:
            current_step_id = str(progress.get("current_step_id") or "")
            company_campaign_lead_id = str(progress.get("company_campaign_lead_id") or "")
            company_campaign_id = str(progress.get("company_campaign_id") or "")
            if not current_step_id or not company_campaign_lead_id or not company_campaign_id:
                raise ValueError(f"incomplete progress row id={progress_id}")

            step_rows = (
                supabase.table("campaign_sequence_steps")
                .select("*")
                .eq("id", current_step_id)
                .is_("deleted_at", "null")
                .execute()
                .data
                or []
            )
            if not step_rows:
                raise ValueError(f"step not found for progress id={progress_id}")
            step = step_rows[0]

            lead_rows = (
                supabase.table("company_campaign_leads")
                .select("*")
                .eq("id", company_campaign_lead_id)
                .is_("deleted_at", "null")
                .execute()
                .data
                or []
            )
            if not lead_rows:
                raise ValueError(f"lead not found for progress id={progress_id}")
            lead = lead_rows[0]

            campaign = _get_campaign(company_campaign_id)
            org_id = str(campaign["org_id"])
            lead_provider_ids = _get_lead_provider_id_map(org_id, company_campaign_lead_id)
            step_order = int(step.get("step_order") or progress.get("current_step_order") or 0)
            lead_override_rows = (
                supabase.table("campaign_lead_step_content")
                .select("action_config_override")
                .eq("org_id", org_id)
                .eq("company_campaign_id", company_campaign_id)
                .eq("company_campaign_lead_id", company_campaign_lead_id)
                .eq("step_order", step_order)
                .execute()
                .data
                or []
            )
            lead_override = (
                lead_override_rows[0].get("action_config_override")
                if lead_override_rows
                else None
            )
            merged_step = dict(step)
            merged_step["action_config"] = _merge_action_config(
                step.get("action_config") or {},
                lead_override if isinstance(lead_override, dict) else None,
            )

            result.leads_processed += 1
            if dry_run:
                continue

            if merged_step.get("skip_if"):
                if should_skip_step(
                    skip_if=merged_step["skip_if"],
                    lead_id=company_campaign_lead_id,
                    campaign_id=company_campaign_id,
                    org_id=org_id,
                ):
                    (
                        supabase.table("campaign_lead_progress")
                        .update(
                            {
                                "step_status": "skipped",
                                "attempts": int(progress.get("attempts") or 0),
                                "last_error": None,
                                "updated_at": _to_iso(_now_utc()),
                            }
                        )
                        .eq("id", progress_id)
                        .eq("org_id", org_id)
                        .execute()
                    )
                    _write_campaign_event(
                        campaign=campaign,
                        progress=progress,
                        step=merged_step,
                        event_type=f"step_{merged_step['action_type']}_skipped",
                        provider_slug=None,
                        payload={"skip_if": merged_step.get("skip_if")},
                    )
                    if _advance_progress_to_next_or_complete(
                        progress_id=progress_id,
                        org_id=org_id,
                        campaign_id=company_campaign_id,
                        current_step_order=int(progress.get("current_step_order") or 0),
                        current_step_status="skipped",
                    ):
                        result.leads_completed += 1
                        incr_metric("orchestrator.steps.completed")
                    incr_metric("orchestrator.steps.skipped")
                    continue

            (
                supabase.table("campaign_lead_progress")
                .update({"step_status": "executing", "updated_at": _to_iso(_now_utc())})
                .eq("id", progress_id)
                .eq("org_id", org_id)
                .execute()
            )

            execution_result = execute_step(
                org_id=org_id,
                step=merged_step,
                lead=lead,
                lead_provider_ids=lead_provider_ids,
            )
            result.steps_executed += 1

            channel = str(merged_step.get("channel") or "unknown")
            provider_slug = execution_result.provider_slug or "unknown"

            if execution_result.success:
                result.steps_succeeded += 1
                incr_metric(
                    "orchestrator.steps.executed",
                    channel=channel,
                    provider_slug=provider_slug,
                    outcome="success",
                )
                (
                    supabase.table("campaign_lead_progress")
                    .update(
                        {
                            "step_status": "executed",
                            "executed_at": _to_iso(now),
                            "attempts": int(progress.get("attempts") or 0) + 1,
                            "last_error": None,
                            "updated_at": _to_iso(_now_utc()),
                        }
                    )
                    .eq("id", progress_id)
                    .eq("org_id", org_id)
                    .execute()
                )
                _write_campaign_event(
                    campaign=campaign,
                    progress=progress,
                    step=merged_step,
                    event_type=f"step_{merged_step['action_type']}_succeeded",
                    provider_slug=execution_result.provider_slug,
                    payload=execution_result.raw_response,
                )

                external_id = execution_result.external_id
                provider_id = merged_step.get("provider_id")
                if external_id and provider_id:
                    _upsert_lead_provider_external_id(
                        org_id=org_id,
                        company_campaign_lead_id=company_campaign_lead_id,
                        provider_id=str(provider_id),
                        external_id=str(external_id),
                    )

                if _advance_progress_to_next_or_complete(
                    progress_id=progress_id,
                    org_id=org_id,
                    campaign_id=company_campaign_id,
                    current_step_order=int(progress.get("current_step_order") or 0),
                    current_step_status="executed",
                ):
                    result.leads_completed += 1
                    incr_metric("orchestrator.steps.completed")
                continue

            incr_metric(
                "orchestrator.steps.executed",
                channel=channel,
                provider_slug=provider_slug,
                outcome="failure",
            )
            attempts = int(progress.get("attempts") or 0) + 1
            _write_campaign_event(
                campaign=campaign,
                progress=progress,
                step=merged_step,
                event_type=f"step_{merged_step['action_type']}_failed",
                provider_slug=execution_result.provider_slug,
                payload=execution_result.raw_response or {"error": execution_result.error_message},
            )
            if execution_result.retryable:
                if attempts >= settings.orchestrator_max_retries:
                    result.steps_failed += 1
                    incr_metric("orchestrator.steps.failed_terminal")
                    (
                        supabase.table("campaign_lead_progress")
                        .update(
                            {
                                "step_status": "failed",
                                "attempts": attempts,
                                "last_error": execution_result.error_message,
                                "next_execute_at": None,
                                "updated_at": _to_iso(_now_utc()),
                            }
                        )
                        .eq("id", progress_id)
                        .eq("org_id", org_id)
                        .execute()
                    )
                else:
                    result.steps_retried += 1
                    incr_metric("orchestrator.steps.retried")
                    (
                        supabase.table("campaign_lead_progress")
                        .update(
                            {
                                "step_status": "pending",
                                "attempts": attempts,
                                "last_error": execution_result.error_message,
                                "next_execute_at": _to_iso(_next_retry_ts(attempts)),
                                "updated_at": _to_iso(_now_utc()),
                            }
                        )
                        .eq("id", progress_id)
                        .eq("org_id", org_id)
                        .execute()
                    )
            else:
                result.steps_failed += 1
                incr_metric("orchestrator.steps.failed_terminal")
                (
                    supabase.table("campaign_lead_progress")
                    .update(
                        {
                            "step_status": "failed",
                            "attempts": attempts,
                            "last_error": execution_result.error_message,
                            "next_execute_at": None,
                            "updated_at": _to_iso(_now_utc()),
                        }
                    )
                    .eq("id", progress_id)
                    .eq("org_id", org_id)
                    .execute()
                )
        except Exception as exc:
            result.errors.append(f"progress_id={progress_id}: {exc}")
            log_event("orchestrator_progress_processing_failed", progress_id=progress_id, error=str(exc))

    incr_metric("orchestrator.tick.leads_processed", value=result.leads_processed)
    return result
