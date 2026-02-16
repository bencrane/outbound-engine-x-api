from pydantic import BaseModel, EmailStr, field_validator
from datetime import datetime
from typing import Literal
from src.auth.permissions import normalize_role


RoleInput = Literal["org_admin", "company_admin", "company_member", "admin", "user"]
RoleCanonical = Literal["org_admin", "company_admin", "company_member"]


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    company_id: str | None = None
    name_first: str | None = None
    name_last: str | None = None
    role: RoleInput = "company_member"

    @field_validator("role", mode="before")
    @classmethod
    def _normalize_role(cls, value: str) -> str:
        return normalize_role(value)


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    password: str | None = None
    company_id: str | None = None
    name_first: str | None = None
    name_last: str | None = None
    role: RoleInput | None = None

    @field_validator("role", mode="before")
    @classmethod
    def _normalize_role(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_role(value)


class UserResponse(BaseModel):
    id: str
    email: str
    company_id: str | None
    name_first: str | None
    name_last: str | None
    role: RoleCanonical
    created_at: datetime
    updated_at: datetime

    @field_validator("role", mode="before")
    @classmethod
    def _normalize_role(cls, value: str) -> str:
        return normalize_role(value)
