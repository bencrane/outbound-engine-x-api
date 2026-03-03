from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.db import supabase
from src.providers.emailbison.client import EmailBisonProviderError, compose_new_email
from src.providers.heyreach.client import HeyReachProviderError, add_campaign_leads
from src.providers.lob.client import LobProviderError, create_letter, create_postcard
from src.providers.voicedrop.client import VoiceDropProviderError, send_ringless_voicemail


class StepExecutionError(Exception):
    """Raised when a step execution fails."""

    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


@dataclass
class StepExecutionResult:
    success: bool
    provider_slug: str
    action_type: str
    external_id: str | None = None
    raw_response: dict | None = None
    error_message: str | None = None
    retryable: bool = False


def get_org_provider_credentials(org_id: str, provider_slug: str) -> dict[str, str | None]:
    """Resolve provider credentials from org provider_configs."""
    result = (
        supabase.table("organizations")
        .select("provider_configs")
        .eq("id", org_id)
        .is_("deleted_at", "null")
        .execute()
    )
    if not result.data:
        raise StepExecutionError("Organization not found", retryable=False)

    provider_configs = result.data[0].get("provider_configs") or {}
    provider_config = provider_configs.get(provider_slug) or {}
    api_key = provider_config.get("api_key")
    if not api_key:
        raise StepExecutionError(f"Missing org-level {provider_slug} API key", retryable=False)

    return {"api_key": api_key, "instance_url": provider_config.get("instance_url")}


def get_provider_slug(provider_id: str) -> str:
    """Resolve provider slug from providers table."""
    result = (
        supabase.table("providers")
        .select("slug")
        .eq("id", provider_id)
        .is_("deleted_at", "null")
        .execute()
    )
    if not result.data:
        raise StepExecutionError("Provider not found", retryable=False)
    slug = result.data[0].get("slug")
    if not slug:
        raise StepExecutionError("Provider slug missing", retryable=False)
    return str(slug)


def _extract_external_id(raw_response: dict[str, Any]) -> str | None:
    for key in ("id", "reply_id", "email_id", "message_id", "lead_id", "external_id"):
        value = raw_response.get(key)
        if value is not None:
            return str(value)
    return None


def _build_to_emails(lead: dict[str, Any]) -> list[dict[str, str]]:
    email = str(lead.get("email") or "").strip()
    if not email:
        raise StepExecutionError("Lead is missing email for email touch", retryable=False)

    first_name = str(lead.get("first_name") or "").strip()
    last_name = str(lead.get("last_name") or "").strip()
    full_name = " ".join(part for part in [first_name, last_name] if part).strip()
    recipient: dict[str, str] = {"email_address": email}
    if full_name:
        recipient["name"] = full_name
    return [recipient]


def _build_heyreach_lead_payload(
    lead: dict[str, Any],
    lead_provider_ids: dict[str, str],
) -> dict[str, Any]:
    payload: dict[str, Any] = {}

    first_name = str(lead.get("first_name") or "").strip()
    last_name = str(lead.get("last_name") or "").strip()
    if first_name:
        payload["firstName"] = first_name
    if last_name:
        payload["lastName"] = last_name

    linkedin_url = (
        lead.get("linkedin_url")
        or lead.get("linkedin_profile_url")
        or lead.get("linkedin_profile")
        or lead.get("profile_url")
    )
    if linkedin_url:
        payload["linkedinUrl"] = str(linkedin_url)

    email = lead.get("email")
    if email:
        payload["emailAddress"] = str(email)

    company_name = lead.get("company_name")
    if company_name:
        payload["companyName"] = str(company_name)

    heyreach_lead_id = lead_provider_ids.get("heyreach")
    if heyreach_lead_id:
        payload["id"] = str(heyreach_lead_id)

    if not payload:
        raise StepExecutionError("Lead has no usable fields for HeyReach injection", retryable=False)
    return payload


def execute_step(
    *,
    org_id: str,
    step: dict,
    lead: dict,
    lead_provider_ids: dict[str, str],
) -> StepExecutionResult:
    provider_slug = "unknown"
    action_type = str(step.get("action_type") or "")
    try:
        provider_slug = get_provider_slug(str(step.get("provider_id") or ""))
        credentials = get_org_provider_credentials(org_id, provider_slug)
        api_key = credentials["api_key"]
        instance_url = credentials.get("instance_url")

        channel = str(step.get("channel") or "")
        execution_mode = str(step.get("execution_mode") or "")
        action_config = step.get("action_config") or {}
        if not isinstance(action_config, dict):
            raise StepExecutionError("Step action_config must be an object", retryable=False)

        if channel == "email" and execution_mode == "direct_single_touch":
            subject = str(action_config.get("subject") or "").strip()
            message = str(action_config.get("message") or action_config.get("body") or "").strip()
            sender_email_id = action_config.get("sender_email_id")

            if not subject:
                return StepExecutionResult(
                    success=False,
                    provider_slug=provider_slug,
                    action_type=action_type,
                    error_message="Missing subject for email step",
                    retryable=False,
                )
            if not message:
                return StepExecutionResult(
                    success=False,
                    provider_slug=provider_slug,
                    action_type=action_type,
                    error_message="Missing message/body for email step",
                    retryable=False,
                )
            if sender_email_id is None:
                return StepExecutionResult(
                    success=False,
                    provider_slug=provider_slug,
                    action_type=action_type,
                    error_message="Missing sender_email_id for email step",
                    retryable=False,
                )

            response = compose_new_email(
                api_key=str(api_key),
                instance_url=instance_url,
                to_emails=_build_to_emails(lead),
                subject=subject,
                message=message,
                sender_email_id=int(sender_email_id),
            )
            return StepExecutionResult(
                success=True,
                provider_slug=provider_slug,
                action_type=action_type,
                external_id=_extract_external_id(response),
                raw_response=response,
            )

        if channel == "linkedin" and execution_mode == "campaign_mediated":
            provider_campaign_id = step.get("provider_campaign_id")
            if not provider_campaign_id:
                return StepExecutionResult(
                    success=False,
                    provider_slug=provider_slug,
                    action_type=action_type,
                    error_message="Missing provider_campaign_id for campaign-mediated LinkedIn step",
                    retryable=False,
                )

            lead_payload = _build_heyreach_lead_payload(lead, lead_provider_ids)
            response = add_campaign_leads(
                api_key=str(api_key),
                campaign_id=str(provider_campaign_id),
                leads=[lead_payload],
            )
            return StepExecutionResult(
                success=True,
                provider_slug=provider_slug,
                action_type=action_type,
                external_id=_extract_external_id(response),
                raw_response=response,
            )

        if channel == "direct_mail" and execution_mode == "direct_single_touch":
            if action_type == "send_postcard":
                response = create_postcard(
                    api_key=str(api_key),
                    payload=action_config,
                )
            elif action_type == "send_letter":
                response = create_letter(
                    api_key=str(api_key),
                    payload=action_config,
                )
            else:
                return StepExecutionResult(
                    success=False,
                    provider_slug=provider_slug,
                    action_type=action_type,
                    error_message=f"Unsupported direct mail action type: {action_type}",
                    retryable=False,
                )

            return StepExecutionResult(
                success=True,
                provider_slug=provider_slug,
                action_type=action_type,
                external_id=_extract_external_id(response),
                raw_response=response,
            )

        if channel == "voicemail" and execution_mode == "direct_single_touch":
            to_phone = str(lead.get("phone") or lead.get("phone_number") or "").strip()
            if not to_phone:
                return StepExecutionResult(
                    success=False,
                    provider_slug=provider_slug,
                    action_type=action_type,
                    error_message="Lead is missing phone for voicemail touch",
                    retryable=False,
                )

            from_number = str(action_config.get("from_number") or "").strip()
            if not from_number:
                return StepExecutionResult(
                    success=False,
                    provider_slug=provider_slug,
                    action_type=action_type,
                    error_message="Missing from_number for voicemail step",
                    retryable=False,
                )

            voice_clone_id_raw = action_config.get("voice_clone_id")
            script_raw = action_config.get("script")
            recording_url_raw = action_config.get("recording_url")

            voice_clone_id = str(voice_clone_id_raw).strip() if voice_clone_id_raw is not None else None
            if voice_clone_id == "":
                voice_clone_id = None
            script = str(script_raw).strip() if script_raw is not None else None
            if script == "":
                script = None
            recording_url = str(recording_url_raw).strip() if recording_url_raw is not None else None
            if recording_url == "":
                recording_url = None

            validate_recipient_phone = bool(action_config.get("validate_recipient_phone", False))
            webhook_raw = action_config.get("send_status_to_webhook")
            send_status_to_webhook = str(webhook_raw).strip() if webhook_raw is not None else None
            if send_status_to_webhook == "":
                send_status_to_webhook = None

            response = send_ringless_voicemail(
                api_key=str(api_key),
                to=to_phone,
                from_number=from_number,
                voice_clone_id=voice_clone_id,
                script=script,
                recording_url=recording_url,
                validate_recipient_phone=validate_recipient_phone,
                send_status_to_webhook=send_status_to_webhook,
            )
            return StepExecutionResult(
                success=True,
                provider_slug=provider_slug,
                action_type=action_type,
                external_id=_extract_external_id(response),
                raw_response=response,
            )

        return StepExecutionResult(
            success=False,
            provider_slug=provider_slug,
            action_type=action_type,
            error_message=f"Unsupported channel/execution_mode: {channel}/{execution_mode}",
            retryable=False,
        )
    except StepExecutionError as exc:
        return StepExecutionResult(
            success=False,
            provider_slug=provider_slug,
            action_type=action_type,
            error_message=str(exc),
            retryable=exc.retryable,
        )
    except (EmailBisonProviderError, HeyReachProviderError, LobProviderError, VoiceDropProviderError) as exc:
        return StepExecutionResult(
            success=False,
            provider_slug=provider_slug,
            action_type=action_type,
            error_message=str(exc),
            retryable=bool(getattr(exc, "retryable", False)),
        )
