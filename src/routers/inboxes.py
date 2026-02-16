from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.auth import AuthContext, get_current_auth
from src.db import supabase
from src.models.inboxes import InboxResponse


router = APIRouter(prefix="/api/inboxes", tags=["inboxes"])


@router.get("/", response_model=list[InboxResponse])
async def list_inboxes(
    company_id: str | None = Query(None),
    all_companies: bool = Query(False),
    auth: AuthContext = Depends(get_current_auth),
):
    """
    Capability-facing inbox list endpoint.

    - Session users with company scope only see their company inboxes.
    - Org-level callers can either provide `company_id`, or pass `all_companies=true` for an org-wide view.
    """
    resolved_company_id: str | None = company_id
    if auth.company_id:
        if all_companies:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="All-companies view is admin only")
        if company_id and company_id != auth.company_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")
        resolved_company_id = auth.company_id
    else:
        if auth.role != "admin":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
        if all_companies and company_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="company_id cannot be combined with all_companies=true",
            )
        if not all_companies and not company_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="company_id is required for org-level callers",
            )

    if resolved_company_id:
        company_check = supabase.table("companies").select("id").eq(
            "id", resolved_company_id
        ).eq("org_id", auth.org_id).is_("deleted_at", "null").execute()
        if not company_check.data:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")

    query = supabase.table("company_inboxes").select(
        "id, company_id, provider_id, external_account_id, email, display_name, status, warmup_enabled, updated_at"
    ).eq("org_id", auth.org_id).is_("deleted_at", "null")
    if resolved_company_id:
        query = query.eq("company_id", resolved_company_id)
    result = query.execute()
    return result.data
