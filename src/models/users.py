from pydantic import BaseModel, EmailStr
from datetime import datetime
from typing import Literal


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    company_id: str | None = None
    name_first: str | None = None
    name_last: str | None = None
    role: Literal["admin", "user"] = "user"


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    password: str | None = None
    company_id: str | None = None
    name_first: str | None = None
    name_last: str | None = None
    role: Literal["admin", "user"] | None = None


class UserResponse(BaseModel):
    id: str
    email: str
    company_id: str | None
    name_first: str | None
    name_last: str | None
    role: Literal["admin", "user"]
    created_at: datetime
    updated_at: datetime
