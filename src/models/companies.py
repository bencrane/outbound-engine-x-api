from pydantic import BaseModel
from datetime import datetime


class CompanyCreate(BaseModel):
    name: str
    domain: str | None = None


class CompanyUpdate(BaseModel):
    name: str | None = None
    domain: str | None = None
    status: str | None = None


class CompanyResponse(BaseModel):
    id: str
    name: str
    domain: str | None
    status: str
    created_at: datetime
    updated_at: datetime
