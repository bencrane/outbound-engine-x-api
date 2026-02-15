from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from src.auth import AuthContext, get_current_auth, require_org_admin
from src.db import supabase
from src.models.organizations import OrganizationResponse, OrganizationUpdate

router = APIRouter(prefix="/api/organizations", tags=["organizations"])


@router.get("/", response_model=list[OrganizationResponse])
async def list_organizations(auth: AuthContext = Depends(get_current_auth)):
    """List organizations. Returns only the authenticated user's org."""
    result = supabase.table("organizations").select("*").eq(
        "id", auth.org_id
    ).is_("deleted_at", "null").execute()

    return result.data


@router.get("/{org_id}", response_model=OrganizationResponse)
async def get_organization(org_id: str, auth: AuthContext = Depends(get_current_auth)):
    """Get organization by ID. Must match authenticated org."""
    if org_id != auth.org_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    result = supabase.table("organizations").select("*").eq(
        "id", org_id
    ).is_("deleted_at", "null").single().execute()

    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    return result.data


@router.put("/{org_id}", response_model=OrganizationResponse)
async def update_organization(
    org_id: str,
    data: OrganizationUpdate,
    auth: AuthContext = Depends(require_org_admin),
):
    """Update organization. Must match authenticated org."""
    if org_id != auth.org_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    update_data = data.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")

    update_data["updated_at"] = datetime.now(timezone.utc).isoformat()

    result = supabase.table("organizations").update(update_data).eq(
        "id", org_id
    ).is_("deleted_at", "null").execute()

    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    return result.data[0]
