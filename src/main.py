from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.routers import (
    organizations,
    companies,
    users,
    entitlements,
    auth_routes,
    super_admin,
    internal_provisioning,
    inboxes,
    campaigns,
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

app.include_router(organizations.router)
app.include_router(companies.router)
app.include_router(users.router)
app.include_router(entitlements.router)
app.include_router(auth_routes.router)
app.include_router(super_admin.router)
app.include_router(internal_provisioning.router)
app.include_router(inboxes.router)
app.include_router(campaigns.router)
app.include_router(webhooks.router)
app.include_router(analytics.router)


@app.get("/")
async def root():
    return {"status": "ok", "service": "outbound-engine-x"}


@app.get("/health")
async def health():
    return {"status": "healthy"}
