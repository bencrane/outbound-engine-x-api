from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from src.auth import AuthContext, require_org_admin
from src.db import supabase
from src.models.companies import CompanyCreate, CompanyResponse, CompanyUpdate

router = APIRouter(prefix="/api/companies", tags=["companies"])


@router.get("/", response_model=list[CompanyResponse])
async def list_companies(auth: AuthContext = Depends(require_org_admin)):
    """List all companies in the organization."""
    result = supabase.table("companies").select("*").eq(
        "org_id", auth.org_id
    ).is_("deleted_at", "null").execute()

    return result.data


@router.post("/", response_model=CompanyResponse, status_code=status.HTTP_201_CREATED)
async def create_company(data: CompanyCreate, auth: AuthContext = Depends(require_org_admin)):
    """Create a new company in the organization."""
    insert_data = {
        "org_id": auth.org_id,
        "name": data.name,
        "domain": data.domain,
    }

    result = supabase.table("companies").insert(insert_data).execute()

    return result.data[0]


@router.get("/{company_id}", response_model=CompanyResponse)
async def get_company(company_id: str, auth: AuthContext = Depends(require_org_admin)):
    """Get a company by ID."""
    result = supabase.table("companies").select("*").eq(
        "id", company_id
    ).eq("org_id", auth.org_id).is_("deleted_at", "null").single().execute()

    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")

    return result.data


@router.put("/{company_id}", response_model=CompanyResponse)
async def update_company(
    company_id: str,
    data: CompanyUpdate,
    auth: AuthContext = Depends(require_org_admin),
):
    """Update a company."""
    update_data = data.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")

    update_data["updated_at"] = datetime.now(timezone.utc).isoformat()

    result = supabase.table("companies").update(update_data).eq(
        "id", company_id
    ).eq("org_id", auth.org_id).is_("deleted_at", "null").execute()

    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")

    return result.data[0]


@router.delete("/{company_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_company(company_id: str, auth: AuthContext = Depends(require_org_admin)):
    """Soft delete a company."""
    result = supabase.table("companies").update({
        "deleted_at": datetime.now(timezone.utc).isoformat()
    }).eq("id", company_id).eq("org_id", auth.org_id).is_("deleted_at", "null").execute()

    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")

    return None
