from pydantic import BaseModel, EmailStr
from datetime import datetime


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    company_id: str | None = None
    name_first: str | None = None
    name_last: str | None = None
    role: str = "user"


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    password: str | None = None
    company_id: str | None = None
    name_first: str | None = None
    name_last: str | None = None
    role: str | None = None


class UserResponse(BaseModel):
    id: str
    email: str
    company_id: str | None
    name_first: str | None
    name_last: str | None
    role: str
    created_at: datetime
    updated_at: datetime
