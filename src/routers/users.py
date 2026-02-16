from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status, Query
from passlib.hash import bcrypt
from src.auth import AuthContext, require_org_admin
from src.auth.permissions import is_org_admin_role, normalize_role
from src.db import supabase
from src.models.users import UserCreate, UserResponse, UserUpdate

router = APIRouter(prefix="/api/users", tags=["users"])


def _validate_role_company_pair(
    *,
    role: str,
    company_id: str | None,
    auth: AuthContext,
) -> tuple[str, str | None]:
    normalized_role = normalize_role(role)
    if normalized_role == "org_admin":
        if not is_org_admin_role(auth.role):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
        return normalized_role, None
    if not company_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="company_id is required for company-level roles",
        )
    return normalized_role, company_id


@router.get("/", response_model=list[UserResponse])
async def list_users(
    company_id: str | None = Query(None),
    auth: AuthContext = Depends(require_org_admin),
):
    """List users in the organization. Optionally filter by company_id."""
    if company_id:
        company_check = supabase.table("companies").select("id").eq(
            "id", company_id
        ).eq("org_id", auth.org_id).is_("deleted_at", "null").execute()
        if not company_check.data:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")

    query = supabase.table("users").select(
        "id, email, company_id, name_first, name_last, role, created_at, updated_at"
    ).eq("org_id", auth.org_id).is_("deleted_at", "null")

    if company_id:
        query = query.eq("company_id", company_id)

    result = query.execute()
    return result.data


@router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(data: UserCreate, auth: AuthContext = Depends(require_org_admin)):
    """Create a new user in the organization."""
    role, company_id = _validate_role_company_pair(role=data.role, company_id=data.company_id, auth=auth)

    # Validate company belongs to org if provided
    if company_id:
        company_check = supabase.table("companies").select("id").eq(
            "id", company_id
        ).eq("org_id", auth.org_id).is_("deleted_at", "null").execute()

        if not company_check.data:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Company not found")

    insert_data = {
        "org_id": auth.org_id,
        "email": data.email,
        "password_hash": bcrypt.hash(data.password),
        "company_id": company_id,
        "name_first": data.name_first,
        "name_last": data.name_last,
        "role": role,
    }

    result = supabase.table("users").insert(insert_data).execute()
    user = result.data[0]

    # Remove password_hash from response
    return UserResponse(
        id=user["id"],
        email=user["email"],
        company_id=user["company_id"],
        name_first=user["name_first"],
        name_last=user["name_last"],
        role=user["role"],
        created_at=user["created_at"],
        updated_at=user["updated_at"],
    )


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(user_id: str, auth: AuthContext = Depends(require_org_admin)):
    """Get a user by ID."""
    result = supabase.table("users").select(
        "id, email, company_id, name_first, name_last, role, created_at, updated_at"
    ).eq("id", user_id).eq("org_id", auth.org_id).is_("deleted_at", "null").single().execute()

    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    return result.data


@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str,
    data: UserUpdate,
    auth: AuthContext = Depends(require_org_admin),
):
    """Update a user."""
    existing_result = supabase.table("users").select(
        "id, role, company_id"
    ).eq("id", user_id).eq("org_id", auth.org_id).is_("deleted_at", "null").execute()
    if not existing_result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    existing_user = existing_result.data[0]

    update_data = data.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")

    # Hash password if being updated
    if "password" in update_data:
        update_data["password_hash"] = bcrypt.hash(update_data.pop("password"))

    target_role = normalize_role(update_data.get("role", existing_user["role"]))
    requested_company_id = (
        update_data["company_id"] if "company_id" in update_data else existing_user.get("company_id")
    )
    target_role, target_company_id = _validate_role_company_pair(
        role=target_role,
        company_id=requested_company_id,
        auth=auth,
    )
    update_data["role"] = target_role
    update_data["company_id"] = target_company_id

    # Validate company belongs to org when company-level role is used
    if target_company_id:
        company_check = supabase.table("companies").select("id").eq(
            "id", target_company_id
        ).eq("org_id", auth.org_id).is_("deleted_at", "null").execute()

        if not company_check.data:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Company not found")

    update_data["updated_at"] = datetime.now(timezone.utc).isoformat()

    result = supabase.table("users").update(update_data).eq(
        "id", user_id
    ).eq("org_id", auth.org_id).is_("deleted_at", "null").execute()

    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user = result.data[0]
    return UserResponse(
        id=user["id"],
        email=user["email"],
        company_id=user["company_id"],
        name_first=user["name_first"],
        name_last=user["name_last"],
        role=user["role"],
        created_at=user["created_at"],
        updated_at=user["updated_at"],
    )


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: str, auth: AuthContext = Depends(require_org_admin)):
    """Soft delete a user."""
    result = supabase.table("users").update({
        "deleted_at": datetime.now(timezone.utc).isoformat()
    }).eq("id", user_id).eq("org_id", auth.org_id).is_("deleted_at", "null").execute()

    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    return None
