import hashlib
from datetime import datetime, timezone
from fastapi import Header, HTTPException, status
from src.auth.context import AuthContext, SuperAdminContext
from src.auth.jwt import decode_access_token, decode_super_admin_token
from src.db import supabase


def _hash_token(token: str) -> str:
    """SHA-256 hash a token for lookup."""
    return hashlib.sha256(token.encode()).hexdigest()


def _extract_bearer_token(authorization: str | None) -> str | None:
    """Extract token from 'Bearer <token>' header."""
    if not authorization:
        return None
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1]


async def _validate_api_token(token: str) -> AuthContext | None:
    """Validate API token against database. Returns AuthContext or None."""
    token_hash = _hash_token(token)

    result = supabase.table("api_tokens").select(
        "id, org_id, user_id, expires_at"
    ).eq("token_hash", token_hash).execute()

    if not result.data:
        return None

    token_record = result.data[0]

    # Check expiration
    if token_record.get("expires_at"):
        expires_at = datetime.fromisoformat(token_record["expires_at"].replace("Z", "+00:00"))
        if expires_at < datetime.now(timezone.utc):
            return None

    # Update last_used_at
    supabase.table("api_tokens").update({
        "last_used_at": datetime.now(timezone.utc).isoformat()
    }).eq("id", token_record["id"]).execute()

    return AuthContext(
        org_id=token_record["org_id"],
        user_id=token_record["user_id"],
        token_id=token_record["id"],
        auth_method="api_token",
    )


async def _validate_jwt(token: str) -> AuthContext | None:
    """Validate JWT session token. Returns AuthContext or None."""
    payload = decode_access_token(token)
    if not payload:
        return None

    return AuthContext(
        org_id=payload["org_id"],
        user_id=payload["sub"],
        company_id=payload.get("company_id"),
        auth_method="session",
    )


async def get_current_auth(authorization: str | None = Header(None)) -> AuthContext:
    """
    Dual auth: tries JWT first (no DB call), falls back to API token.
    Use this for endpoints that accept either auth method.
    """
    token = _extract_bearer_token(authorization)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header",
        )

    # Try JWT first (faster, no DB call)
    auth = await _validate_jwt(token)
    if auth:
        return auth

    # Fall back to API token
    auth = await _validate_api_token(token)
    if auth:
        return auth

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
    )


async def get_current_org(authorization: str | None = Header(None)) -> AuthContext:
    """
    API token only auth. For machine-to-machine endpoints.
    """
    token = _extract_bearer_token(authorization)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header",
        )

    auth = await _validate_api_token(token)
    if not auth:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired API token",
        )

    return auth


async def get_current_user(authorization: str | None = Header(None)) -> AuthContext:
    """
    JWT session only auth. For user-facing endpoints.
    """
    token = _extract_bearer_token(authorization)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header",
        )

    auth = await _validate_jwt(token)
    if not auth:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session",
        )

    return auth


async def get_current_super_admin(authorization: str | None = Header(None)) -> SuperAdminContext:
    """
    Super-admin JWT auth. Validates token type is 'super_admin' and user exists in super_admins table.
    """
    token = _extract_bearer_token(authorization)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header",
        )

    # Decode super-admin JWT
    payload = decode_super_admin_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired super-admin token",
        )

    # Verify super-admin exists in database
    result = supabase.table("super_admins").select("id, email").eq(
        "id", payload["sub"]
    ).execute()

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Super-admin not found",
        )

    super_admin = result.data[0]
    return SuperAdminContext(
        super_admin_id=super_admin["id"],
        email=super_admin["email"],
    )
