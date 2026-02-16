from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from src.routers import (
    organizations,
    companies,
    users,
    entitlements,
    auth_routes,
    super_admin,
    internal_provisioning,
    internal_reconciliation,
    inboxes,
    campaigns,
    linkedin_campaigns,
    webhooks,
    analytics,
)

app = FastAPI(title="Outbound Engine X", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def attach_request_id(request: Request, call_next):
    request_id = (
        request.headers.get("X-Request-ID")
        or request.headers.get("X-Correlation-ID")
        or str(uuid4())
    )
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response

app.include_router(organizations.router)
app.include_router(companies.router)
app.include_router(users.router)
app.include_router(entitlements.router)
app.include_router(auth_routes.router)
app.include_router(super_admin.router)
app.include_router(internal_provisioning.router)
app.include_router(internal_reconciliation.router)
app.include_router(inboxes.router)
app.include_router(campaigns.router)
app.include_router(linkedin_campaigns.router)
app.include_router(webhooks.router)
app.include_router(analytics.router)


@app.get("/")
async def root():
    return {"status": "ok", "service": "outbound-engine-x"}


@app.get("/health")
async def health():
    return {"status": "healthy"}
