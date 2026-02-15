import secrets
import hashlib
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
import bcrypt as bcrypt_lib
from pydantic import BaseModel, EmailStr
from src.auth import SuperAdminContext, get_current_super_admin, create_super_admin_token
from src.db import supabase


def hash_password(password: str) -> str:
    """Hash password using bcrypt."""
    return bcrypt_lib.hashpw(password.encode(), bcrypt_lib.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    """Verify password against hash."""
    return bcrypt_lib.checkpw(password.encode(), password_hash.encode())


router = APIRouter(prefix="/api/super-admin", tags=["super-admin"])


# --- Request/Response Models ---

class SuperAdminLoginRequest(BaseModel):
    email: EmailStr
    password: str


class SuperAdminLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class SuperAdminMeResponse(BaseModel):
    super_admin_id: str
    email: str


class OrganizationCreate(BaseModel):
    name: str
    slug: str


class OrganizationResponse(BaseModel):
    id: str
    name: str
    slug: str
    provider_configs: dict | None = None
    created_at: datetime
    updated_at: datetime


class OrganizationUpdate(BaseModel):
    name: str | None = None
    slug: str | None = None


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    name_first: str | None = None
    name_last: str | None = None
    role: str = "admin"


class UserResponse(BaseModel):
    id: str
    email: str
    company_id: str | None
    name_first: str | None
    name_last: str | None
    role: str
    created_at: datetime
    updated_at: datetime


class CompanyResponse(BaseModel):
    id: str
    name: str


class CapabilityInfo(BaseModel):
    id: str
    slug: str
    name: str
    created_at: datetime


class ProviderInfo(BaseModel):
    id: str
    slug: str
    name: str
    capability_id: str
    capability_slug: str | None = None
    created_at: datetime


class TokenCreateRequest(BaseModel):
    user_id: str
    name: str | None = None
    expires_at: datetime | None = None


class TokenCreateResponse(BaseModel):
    id: str
    token: str
    name: str | None
    expires_at: datetime | None
    created_at: datetime


class ProviderConfigUpdate(BaseModel):
    provider_slug: str    # e.g., "smartlead", "heyreach"
    config: dict          # Provider-specific config (API keys, etc.)


# --- Login (no auth required) ---

@router.post("/login", response_model=SuperAdminLoginResponse)
async def super_admin_login(data: SuperAdminLoginRequest):
    """Login as super-admin, returns JWT with type 'super_admin'."""
    result = supabase.table("super_admins").select(
        "id, email, password_hash"
    ).eq("email", data.email).execute()

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )

    super_admin = result.data[0]

    if not verify_password(data.password, super_admin["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )

    token = create_super_admin_token(super_admin_id=super_admin["id"])
    return SuperAdminLoginResponse(access_token=token)


# --- Me ---

@router.get("/me", response_model=SuperAdminMeResponse)
async def get_me(ctx: SuperAdminContext = Depends(get_current_super_admin)):
    """Get current super-admin info."""
    return SuperAdminMeResponse(
        super_admin_id=ctx.super_admin_id,
        email=ctx.email,
    )


# --- Organizations CRUD ---

@router.post("/organizations", response_model=OrganizationResponse, status_code=status.HTTP_201_CREATED)
async def create_organization(
    data: OrganizationCreate,
    ctx: SuperAdminContext = Depends(get_current_super_admin),
):
    """Create a new organization."""
    result = supabase.table("organizations").insert({
        "name": data.name,
        "slug": data.slug,
    }).execute()

    return result.data[0]


@router.get("/organizations", response_model=list[OrganizationResponse])
async def list_organizations(ctx: SuperAdminContext = Depends(get_current_super_admin)):
    """List ALL organizations."""
    result = supabase.table("organizations").select("*").is_(
        "deleted_at", "null"
    ).execute()

    return result.data


@router.get("/organizations/{org_id}", response_model=OrganizationResponse)
async def get_organization(
    org_id: str,
    ctx: SuperAdminContext = Depends(get_current_super_admin),
):
    """Get any organization by ID."""
    result = supabase.table("organizations").select("*").eq(
        "id", org_id
    ).is_("deleted_at", "null").execute()

    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    return result.data[0]


@router.put("/organizations/{org_id}", response_model=OrganizationResponse)
async def update_organization(
    org_id: str,
    data: OrganizationUpdate,
    ctx: SuperAdminContext = Depends(get_current_super_admin),
):
    """Update any organization."""
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


@router.delete("/organizations/{org_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_organization(
    org_id: str,
    ctx: SuperAdminContext = Depends(get_current_super_admin),
):
    """Soft delete an organization."""
    result = supabase.table("organizations").update({
        "deleted_at": datetime.now(timezone.utc).isoformat()
    }).eq("id", org_id).is_("deleted_at", "null").execute()

    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    return None


# --- Org-scoped operations ---

@router.post("/organizations/{org_id}/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_org_user(
    org_id: str,
    data: UserCreate,
    ctx: SuperAdminContext = Depends(get_current_super_admin),
):
    """Create an admin user within an org (bootstraps the first user)."""
    # Verify org exists
    org_check = supabase.table("organizations").select("id").eq(
        "id", org_id
    ).is_("deleted_at", "null").execute()

    if not org_check.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    result = supabase.table("users").insert({
        "org_id": org_id,
        "email": data.email,
        "password_hash": hash_password(data.password),
        "name_first": data.name_first,
        "name_last": data.name_last,
        "role": data.role,
    }).execute()

    user = result.data[0]
    return UserResponse(
        id=user["id"],
        email=user["email"],
        company_id=user.get("company_id"),
        name_first=user["name_first"],
        name_last=user["name_last"],
        role=user["role"],
        created_at=user["created_at"],
        updated_at=user["updated_at"],
    )


@router.get("/organizations/{org_id}/companies", response_model=list[CompanyResponse])
async def list_org_companies(
    org_id: str,
    ctx: SuperAdminContext = Depends(get_current_super_admin),
):
    """List all companies in an organization."""
    result = supabase.table("companies").select("*").eq(
        "org_id", org_id
    ).is_("deleted_at", "null").execute()

    return result.data


@router.get("/organizations/{org_id}/users", response_model=list[UserResponse])
async def list_org_users(
    org_id: str,
    ctx: SuperAdminContext = Depends(get_current_super_admin),
):
    """List all users in an organization."""
    result = supabase.table("users").select(
        "id, email, company_id, name_first, name_last, role, created_at, updated_at"
    ).eq("org_id", org_id).is_("deleted_at", "null").execute()

    return result.data


@router.post("/organizations/{org_id}/api-tokens", response_model=TokenCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_org_api_token(
    org_id: str,
    data: TokenCreateRequest,
    ctx: SuperAdminContext = Depends(get_current_super_admin),
):
    """Create an API token for an org."""
    # Verify org exists
    org_check = supabase.table("organizations").select("id").eq(
        "id", org_id
    ).is_("deleted_at", "null").execute()

    if not org_check.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    # Verify user exists in this org
    user_check = supabase.table("users").select("id").eq(
        "id", data.user_id
    ).eq("org_id", org_id).is_("deleted_at", "null").execute()

    if not user_check.data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User not found in this organization")

    # Generate token
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

    result = supabase.table("api_tokens").insert({
        "org_id": org_id,
        "user_id": data.user_id,
        "token_hash": token_hash,
        "name": data.name,
        "expires_at": data.expires_at.isoformat() if data.expires_at else None,
    }).execute()

    token_record = result.data[0]
    return TokenCreateResponse(
        id=token_record["id"],
        token=raw_token,
        name=token_record["name"],
        expires_at=token_record["expires_at"],
        created_at=token_record["created_at"],
    )


@router.put("/organizations/{org_id}/provider-config")
async def set_provider_config(
    org_id: str,
    data: ProviderConfigUpdate,
    ctx: SuperAdminContext = Depends(get_current_super_admin),
):
    """Set provider config (API keys, etc.) at the org level."""
    # Get current org with provider_configs
    org_result = supabase.table("organizations").select("id, provider_configs").eq(
        "id", org_id
    ).is_("deleted_at", "null").execute()

    if not org_result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    org = org_result.data[0]
    current_configs = org.get("provider_configs") or {}

    # Update the config for this provider
    current_configs[data.provider_slug] = data.config

    # Save back to org
    result = supabase.table("organizations").update({
        "provider_configs": current_configs,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", org_id).execute()

    return {
        "provider": data.provider_slug,
        "config_set": True
    }


# --- System lookups (capabilities & providers) ---

@router.get("/capabilities", response_model=list[CapabilityInfo])
async def list_capabilities(ctx: SuperAdminContext = Depends(get_current_super_admin)):
    """List all capabilities in the system."""
    result = supabase.table("capabilities").select("*").execute()
    return result.data


@router.get("/providers", response_model=list[ProviderInfo])
async def list_providers(ctx: SuperAdminContext = Depends(get_current_super_admin)):
    """List all providers in the system with their capability."""
    result = supabase.table("providers").select("*, capabilities(slug)").execute()

    providers = []
    for p in result.data:
        providers.append(ProviderInfo(
            id=p["id"],
            slug=p["slug"],
            name=p["name"],
            capability_id=p["capability_id"],
            capability_slug=p["capabilities"]["slug"] if p.get("capabilities") else None,
            created_at=p["created_at"],
        ))
    return providers
