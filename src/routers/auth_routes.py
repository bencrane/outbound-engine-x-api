import logging
from fastapi import APIRouter, Depends, HTTPException, status
import bcrypt as bcrypt_lib
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

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def verify_password(password: str, password_hash: str) -> bool:
    """Verify password against hash using bcrypt."""
    try:
        return bcrypt_lib.checkpw(password.encode(), password_hash.encode())
    except Exception as e:
        logger.error(f"Password verification error: {e}")
        return False


@router.post("/login", response_model=LoginResponse)
async def login(data: LoginRequest):
    """Login with email and password, returns JWT."""
    # Email is unique per-org, not globally unique.
    try:
        result = supabase.table("users").select(
            "id, org_id, company_id, email, password_hash"
        ).eq("email", data.email).is_("deleted_at", "null").execute()
    except Exception as e:
        logger.error(f"Database error during login: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database error: {type(e).__name__}"
        )

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )

    matching_users = [
        user for user in result.data
        if verify_password(data.password, user["password_hash"])
    ]

    if not matching_users:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )

    if len(matching_users) > 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ambiguous login: account exists in multiple organizations",
        )

    user = matching_users[0]

    # Create JWT
    token = create_access_token(
        user_id=user["id"],
        org_id=user["org_id"],
        company_id=user["company_id"],
    )

    return LoginResponse(access_token=token)


@router.post("/tokens", response_model=TokenCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_token(data: TokenCreate, auth: AuthContext = Depends(get_current_auth)):
    """Disabled: API token management is super-admin only."""
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="API token management is super-admin only",
    )


@router.get("/tokens", response_model=list[TokenResponse])
async def list_tokens(auth: AuthContext = Depends(get_current_auth)):
    """Disabled: API token management is super-admin only."""
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="API token management is super-admin only",
    )


@router.delete("/tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_token(token_id: str, auth: AuthContext = Depends(get_current_auth)):
    """Disabled: API token management is super-admin only."""
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="API token management is super-admin only",
    )


@router.get("/me", response_model=MeResponse)
async def get_me(auth: AuthContext = Depends(get_current_auth)):
    """Get current user info from AuthContext."""
    return MeResponse(
        user_id=auth.user_id,
        org_id=auth.org_id,
        role=auth.role,
        company_id=auth.company_id,
        auth_method=auth.auth_method,
    )
