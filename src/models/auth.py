from pydantic import BaseModel, EmailStr
from datetime import datetime


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenCreate(BaseModel):
    name: str | None = None
    expires_at: datetime | None = None


class TokenResponse(BaseModel):
    id: str
    name: str | None
    expires_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime


class TokenCreateResponse(BaseModel):
    id: str
    token: str  # Raw token, only returned on creation
    name: str | None
    expires_at: datetime | None
    created_at: datetime


class MeResponse(BaseModel):
    user_id: str
    org_id: str
    company_id: str | None
    auth_method: str
