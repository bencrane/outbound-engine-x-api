from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status, Query
from src.auth import AuthContext, get_current_auth
from src.db import supabase
from src.models.entitlements import EntitlementCreate, EntitlementResponse, EntitlementUpdate

router = APIRouter(prefix="/api/entitlements", tags=["entitlements"])


@router.get("/", response_model=list[EntitlementResponse])
async def list_entitlements(
    company_id: str | None = Query(None),
    auth: AuthContext = Depends(get_current_auth),
):
    """List entitlements in the organization. Optionally filter by company_id."""
    query = supabase.table("company_entitlements").select("*").eq(
        "org_id", auth.org_id
    )

    if company_id:
        query = query.eq("company_id", company_id)

    result = query.execute()
    return result.data


@router.post("/", response_model=EntitlementResponse, status_code=status.HTTP_201_CREATED)
async def create_entitlement(data: EntitlementCreate, auth: AuthContext = Depends(get_current_auth)):
    """Create a new entitlement for a company."""
    # Validate company belongs to org
    company_check = supabase.table("companies").select("id").eq(
        "id", data.company_id
    ).eq("org_id", auth.org_id).is_("deleted_at", "null").execute()

    if not company_check.data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Company not found")

    # Validate capability exists
    capability_check = supabase.table("capabilities").select("id").eq(
        "id", data.capability_id
    ).execute()

    if not capability_check.data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Capability not found")

    # Validate provider exists and matches capability
    provider_check = supabase.table("providers").select("id, capability_id").eq(
        "id", data.provider_id
    ).execute()

    if not provider_check.data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Provider not found")

    if provider_check.data[0]["capability_id"] != data.capability_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provider does not fulfill the specified capability"
        )

    insert_data = {
        "org_id": auth.org_id,
        "company_id": data.company_id,
        "capability_id": data.capability_id,
        "provider_id": data.provider_id,
    }

    result = supabase.table("company_entitlements").insert(insert_data).execute()

    return result.data[0]


@router.get("/{entitlement_id}", response_model=EntitlementResponse)
async def get_entitlement(entitlement_id: str, auth: AuthContext = Depends(get_current_auth)):
    """Get an entitlement by ID."""
    result = supabase.table("company_entitlements").select("*").eq(
        "id", entitlement_id
    ).eq("org_id", auth.org_id).single().execute()

    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entitlement not found")

    return result.data


@router.put("/{entitlement_id}", response_model=EntitlementResponse)
async def update_entitlement(
    entitlement_id: str,
    data: EntitlementUpdate,
    auth: AuthContext = Depends(get_current_auth),
):
    """Update an entitlement (status, provider_config)."""
    update_data = data.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")

    update_data["updated_at"] = datetime.now(timezone.utc).isoformat()

    result = supabase.table("company_entitlements").update(update_data).eq(
        "id", entitlement_id
    ).eq("org_id", auth.org_id).execute()

    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entitlement not found")

    return result.data[0]


@router.delete("/{entitlement_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entitlement(entitlement_id: str, auth: AuthContext = Depends(get_current_auth)):
    """Delete an entitlement."""
    result = supabase.table("company_entitlements").delete().eq(
        "id", entitlement_id
    ).eq("org_id", auth.org_id).execute()

    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entitlement not found")

    return None
