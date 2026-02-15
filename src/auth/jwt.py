from datetime import datetime, timedelta, timezone
from jose import jwt, JWTError
from src.config import settings


def create_access_token(user_id: str, org_id: str, company_id: str | None = None) -> str:
    """Create a signed JWT session token."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expiration_minutes)
    payload = {
        "sub": user_id,
        "org_id": org_id,
        "company_id": company_id,
        "type": "session",
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict | None:
    """Decode and validate a JWT. Returns payload or None if invalid."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        if payload.get("type") != "session":
            return None
        return payload
    except JWTError:
        return None


def create_super_admin_token(super_admin_id: str) -> str:
    """Create a signed JWT for super-admin. No org_id - operates above tenant layer."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expiration_minutes)
    payload = {
        "sub": super_admin_id,
        "type": "super_admin",
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_super_admin_token(token: str) -> dict | None:
    """Decode and validate a super-admin JWT. Returns payload or None if invalid."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        if payload.get("type") != "super_admin":
            return None
        return payload
    except JWTError:
        return None
