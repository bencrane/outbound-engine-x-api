from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.auth import AuthContext, get_current_auth
from src.db import supabase
from src.models.inboxes import InboxResponse


router = APIRouter(prefix="/api/inboxes", tags=["inboxes"])


@router.get("/", response_model=list[InboxResponse])
async def list_inboxes(
    company_id: str | None = Query(None),
    auth: AuthContext = Depends(get_current_auth),
):
    """
    Capability-facing inbox list endpoint.

    - Session users with company scope only see their company inboxes.
    - Org-level callers (no company_id in auth context) must be admin and provide company_id.
    """
    resolved_company_id = company_id
    if auth.company_id:
        if company_id and company_id != auth.company_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")
        resolved_company_id = auth.company_id
    else:
        if auth.role != "admin":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
        if not company_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="company_id is required for org-level callers",
            )

    company_check = supabase.table("companies").select("id").eq(
        "id", resolved_company_id
    ).eq("org_id", auth.org_id).is_("deleted_at", "null").execute()
    if not company_check.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")

    result = supabase.table("company_inboxes").select(
        "id, company_id, provider_id, external_account_id, email, display_name, status, warmup_enabled, updated_at"
    ).eq("org_id", auth.org_id).eq("company_id", resolved_company_id).is_("deleted_at", "null").execute()
    return result.data
