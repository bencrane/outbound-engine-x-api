import secrets
import hashlib
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from passlib.hash import bcrypt
from src.auth import AuthContext, get_current_auth
from src.auth.jwt import create_access_token
from src.db import supabase
from src.models.auth import (
    LoginRequest,
    LoginResponse,
    TokenCreate,
    TokenResponse,
    TokenCreateResponse,
    MeResponse,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
async def login(data: LoginRequest):
    """Login with email and password, returns JWT."""
    # Find user by email (need to search across all orgs for login)
    result = supabase.table("users").select(
        "id, org_id, company_id, email, password_hash"
    ).eq("email", data.email).is_("deleted_at", "null").execute()

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )

    user = result.data[0]

    # Verify password
    if not bcrypt.verify(data.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )

    # Create JWT
    token = create_access_token(
        user_id=user["id"],
        org_id=user["org_id"],
        company_id=user["company_id"],
    )

    return LoginResponse(access_token=token)


@router.post("/tokens", response_model=TokenCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_token(data: TokenCreate, auth: AuthContext = Depends(get_current_auth)):
    """Create a new API token. Returns the raw token (only visible once)."""
    # Generate random token
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

    insert_data = {
        "org_id": auth.org_id,
        "user_id": auth.user_id,
        "token_hash": token_hash,
        "name": data.name,
        "expires_at": data.expires_at.isoformat() if data.expires_at else None,
    }

    result = supabase.table("api_tokens").insert(insert_data).execute()
    token_record = result.data[0]

    return TokenCreateResponse(
        id=token_record["id"],
        token=raw_token,
        name=token_record["name"],
        expires_at=token_record["expires_at"],
        created_at=token_record["created_at"],
    )


@router.get("/tokens", response_model=list[TokenResponse])
async def list_tokens(auth: AuthContext = Depends(get_current_auth)):
    """List API tokens for the org (metadata only, not token values)."""
    result = supabase.table("api_tokens").select(
        "id, name, expires_at, last_used_at, created_at"
    ).eq("org_id", auth.org_id).execute()

    return result.data


@router.delete("/tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_token(token_id: str, auth: AuthContext = Depends(get_current_auth)):
    """Revoke an API token."""
    result = supabase.table("api_tokens").delete().eq(
        "id", token_id
    ).eq("org_id", auth.org_id).execute()

    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token not found")

    return None


@router.get("/me", response_model=MeResponse)
async def get_me(auth: AuthContext = Depends(get_current_auth)):
    """Get current user info from AuthContext."""
    return MeResponse(
        user_id=auth.user_id,
        org_id=auth.org_id,
        company_id=auth.company_id,
        auth_method=auth.auth_method,
    )
