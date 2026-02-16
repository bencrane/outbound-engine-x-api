from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from src.auth import SuperAdminContext, get_current_super_admin
from src.db import supabase
from src.domain.provider_errors import provider_error_detail, provider_error_http_status
from src.models.provisioning import (
    EmailOutreachProvisionRequest,
    EmailOutreachProvisionResponse,
)
from src.models.inboxes import InboxSyncResponse
from src.providers.smartlead.client import SmartleadProviderError, validate_api_key, list_email_accounts
from src.providers.emailbison.client import (
    EmailBisonProviderError,
    validate_api_key as emailbison_validate_api_key,
    list_sender_emails as emailbison_list_sender_emails,
)


router = APIRouter(prefix="/api/internal/provisioning", tags=["internal-provisioning"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _raise_provider_http_error(
    provider: str,
    operation: str,
    exc: SmartleadProviderError | EmailBisonProviderError,
) -> None:
    raise HTTPException(
        status_code=provider_error_http_status(exc),
        detail=provider_error_detail(provider=provider, operation=operation, exc=exc),
    ) from exc


def _get_company(company_id: str) -> dict[str, Any]:
    result = supabase.table("companies").select("id, org_id").eq(
        "id", company_id
    ).is_("deleted_at", "null").execute()
    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")
    return result.data[0]


def _get_email_outreach_capability() -> dict[str, Any]:
    result = supabase.table("capabilities").select("id, slug").eq(
        "slug", "email_outreach"
    ).execute()
    if not result.data:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Capability not configured")
    return result.data[0]


def _get_provider_for_capability(capability_id: str, provider_slug: str = "smartlead") -> dict[str, Any]:
    result = supabase.table("providers").select("id, slug, capability_id").eq(
        "slug", provider_slug
    ).eq("capability_id", capability_id).execute()
    if not result.data:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Provider not configured")
    return result.data[0]


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


def _get_or_create_entitlement(org_id: str, company_id: str, capability_id: str, provider_id: str) -> dict[str, Any]:
    existing = supabase.table("company_entitlements").select("*").eq(
        "org_id", org_id
    ).eq("company_id", company_id).eq("capability_id", capability_id).execute()

    if existing.data:
        entitlement = existing.data[0]
        if entitlement["provider_id"] != provider_id:
            updated = supabase.table("company_entitlements").update({
                "provider_id": provider_id,
                "updated_at": _now_iso(),
            }).eq("id", entitlement["id"]).eq("org_id", org_id).execute()
            return updated.data[0]
        return entitlement

    created = supabase.table("company_entitlements").insert({
        "org_id": org_id,
        "company_id": company_id,
        "capability_id": capability_id,
        "provider_id": provider_id,
        "status": "entitled",
    }).execute()
    return created.data[0]


def _to_response(entitlement: dict[str, Any], provider_slug: str) -> EmailOutreachProvisionResponse:
    provider_config = entitlement.get("provider_config") or {}
    return EmailOutreachProvisionResponse(
        company_id=entitlement["company_id"],
        org_id=entitlement["org_id"],
        capability="email_outreach",
        provider=provider_slug,
        entitlement_status=entitlement["status"],
        provisioning_state=provider_config.get("provisioning_state", "pending_client_mapping"),
        smartlead_client_id=provider_config.get("smartlead_client_id"),
        last_error=provider_config.get("last_provision_error"),
        updated_at=entitlement["updated_at"],
    )


def _parse_external_account(account: dict[str, Any]) -> dict[str, Any] | None:
    external_id = account.get("id") or account.get("email_account_id")
    email = account.get("email") or account.get("from_email") or account.get("email_address")
    if external_id is None or not email:
        return None
    return {
        "external_account_id": str(external_id),
        "email": str(email).lower(),
        "display_name": account.get("from_name") or account.get("name"),
        "warmup_enabled": account.get("warmup_enabled"),
        "raw_payload": account,
    }


@router.post("/email-outreach/{company_id}", response_model=EmailOutreachProvisionResponse)
async def provision_email_outreach(
    company_id: str,
    data: EmailOutreachProvisionRequest,
    ctx: SuperAdminContext = Depends(get_current_super_admin),
):
    """
    Internal provisioning endpoint (super-admin only).

    This validates org/provider wiring and stores provider mapping for the company.
    """
    company = _get_company(company_id)
    capability = _get_email_outreach_capability()
    provider = _get_provider_for_capability(capability["id"], data.provider)
    entitlement = _get_or_create_entitlement(company["org_id"], company_id, capability["id"], provider["id"])

    provider_credentials = _get_org_provider_config(company["org_id"], provider["slug"])
    provider_config = entitlement.get("provider_config") or {}
    try:
        if provider["slug"] == "smartlead":
            validate_api_key(provider_credentials["api_key"])
        elif provider["slug"] == "emailbison":
            emailbison_validate_api_key(
                api_key=provider_credentials["api_key"],
                instance_url=provider_credentials.get("instance_url"),
            )
    except SmartleadProviderError as exc:
        provider_config.update(
            {
                "provisioning_state": "failed",
                "last_provision_error": str(exc),
                "last_provision_attempt_at": _now_iso(),
                "updated_by_super_admin_id": ctx.super_admin_id,
            }
        )
        supabase.table("company_entitlements").update(
            {
                "status": "disconnected",
                "provider_config": provider_config,
                "updated_at": _now_iso(),
            }
        ).eq("id", entitlement["id"]).eq("org_id", company["org_id"]).execute()
        _raise_provider_http_error("smartlead", "email_outreach_provision", exc)
    except EmailBisonProviderError as exc:
        provider_config.update(
            {
                "provisioning_state": "failed",
                "last_provision_error": str(exc),
                "last_provision_attempt_at": _now_iso(),
                "updated_by_super_admin_id": ctx.super_admin_id,
            }
        )
        supabase.table("company_entitlements").update(
            {
                "status": "disconnected",
                "provider_config": provider_config,
                "updated_at": _now_iso(),
            }
        ).eq("id", entitlement["id"]).eq("org_id", company["org_id"]).execute()
        _raise_provider_http_error("emailbison", "email_outreach_provision", exc)

    provider_config.update(
        {
            "smartlead_client_id": data.smartlead_client_id if provider["slug"] == "smartlead" else None,
            "provisioning_state": (
                "connected"
                if provider["slug"] == "emailbison" or data.smartlead_client_id
                else "pending_client_mapping"
            ),
            "last_provision_error": None,
            "last_provision_attempt_at": _now_iso(),
            "updated_by_super_admin_id": ctx.super_admin_id,
        }
    )

    updated = supabase.table("company_entitlements").update(
        {
            "status": (
                "connected"
                if provider["slug"] == "emailbison" or data.smartlead_client_id
                else "entitled"
            ),
            "provider_config": provider_config,
            "updated_at": _now_iso(),
        }
    ).eq("id", entitlement["id"]).eq("org_id", company["org_id"]).execute()

    return _to_response(updated.data[0], provider["slug"])


@router.get("/email-outreach/{company_id}/status", response_model=EmailOutreachProvisionResponse)
async def get_email_outreach_provisioning_status(
    company_id: str,
    ctx: SuperAdminContext = Depends(get_current_super_admin),
):
    """Return current provisioning status for company's email outreach capability."""
    company = _get_company(company_id)
    capability = _get_email_outreach_capability()

    entitlement = supabase.table("company_entitlements").select("*").eq(
        "org_id", company["org_id"]
    ).eq("company_id", company_id).eq("capability_id", capability["id"]).execute()

    if not entitlement.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Email outreach entitlement not found for company",
        )

    provider_result = supabase.table("providers").select("id, slug").eq(
        "id", entitlement.data[0]["provider_id"]
    ).execute()
    if not provider_result.data:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Provider not configured")
    return _to_response(entitlement.data[0], provider_result.data[0]["slug"])


@router.post("/email-outreach/{company_id}/sync-inboxes", response_model=InboxSyncResponse)
async def sync_email_outreach_inboxes(
    company_id: str,
    ctx: SuperAdminContext = Depends(get_current_super_admin),
):
    """
    Sync Smartlead inboxes for a company into local company_inboxes mapping table.
    """
    company = _get_company(company_id)
    capability = _get_email_outreach_capability()

    entitlement_result = supabase.table("company_entitlements").select("*").eq(
        "org_id", company["org_id"]
    ).eq("company_id", company_id).eq("capability_id", capability["id"]).execute()
    if not entitlement_result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Email outreach entitlement not found for company",
        )

    entitlement = entitlement_result.data[0]
    provider = supabase.table("providers").select("id, slug").eq(
        "id", entitlement["provider_id"]
    ).execute()
    if not provider.data:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Provider not configured")
    provider = provider.data[0]
    provider_config = entitlement.get("provider_config") or {}
    smartlead_client_id = provider_config.get("smartlead_client_id")
    if provider["slug"] == "smartlead" and smartlead_client_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="smartlead_client_id is required before inbox sync",
        )

    provider_credentials = _get_org_provider_config(company["org_id"], provider["slug"])

    try:
        if provider["slug"] == "smartlead":
            accounts = list_email_accounts(provider_credentials["api_key"])
        elif provider["slug"] == "emailbison":
            accounts = emailbison_list_sender_emails(
                api_key=provider_credentials["api_key"],
                instance_url=provider_credentials.get("instance_url"),
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported email_outreach provider: {provider['slug']}",
            )
    except SmartleadProviderError as exc:
        _raise_provider_http_error("smartlead", "email_outreach_inbox_sync", exc)
    except EmailBisonProviderError as exc:
        _raise_provider_http_error("emailbison", "email_outreach_inbox_sync", exc)

    synced_count = 0
    skipped_count = 0
    warnings: list[str] = []

    for account in accounts:
        account_client_id = account.get("client_id")
        if (
            provider["slug"] == "smartlead"
            and account_client_id is not None
            and str(account_client_id) != str(smartlead_client_id)
        ):
            skipped_count += 1
            continue

        parsed = _parse_external_account(account)
        if not parsed:
            skipped_count += 1
            continue

        existing = supabase.table("company_inboxes").select("id").eq(
            "org_id", company["org_id"]
        ).eq("company_id", company_id).eq("provider_id", provider["id"]).eq(
            "external_account_id", parsed["external_account_id"]
        ).is_("deleted_at", "null").execute()

        payload = {
            "org_id": company["org_id"],
            "company_id": company_id,
            "provider_id": provider["id"],
            "external_account_id": parsed["external_account_id"],
            "email": parsed["email"],
            "display_name": parsed["display_name"],
            "status": "active",
            "warmup_enabled": parsed["warmup_enabled"],
            "raw_payload": parsed["raw_payload"],
            "updated_at": _now_iso(),
        }

        if existing.data:
            supabase.table("company_inboxes").update(payload).eq(
                "id", existing.data[0]["id"]
            ).eq("org_id", company["org_id"]).execute()
        else:
            payload["created_at"] = _now_iso()
            supabase.table("company_inboxes").insert(payload).execute()
        synced_count += 1

    if synced_count == 0:
        warnings.append("No inboxes were synced; verify Smartlead client/account associations")

    return InboxSyncResponse(
        company_id=company_id,
        synced_count=synced_count,
        skipped_count=skipped_count,
        smartlead_client_id=int(smartlead_client_id) if smartlead_client_id is not None else None,
        updated_at=datetime.now(timezone.utc),
        warnings=warnings,
    )
