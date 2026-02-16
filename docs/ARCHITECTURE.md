# Architecture — Outbound Engine X

## Stack Decisions

| Layer | Choice | Why |
|-------|--------|-----|
| API Framework | FastAPI | Async, Pydantic models, dependency injection for AuthContext |
| Compute | Modal | Consistent with engine-x family, serverless scaling |
| Deployment | Railway | Routing layer in front of Modal, zero-downtime deploys |
| Database | Supabase (Postgres) | Managed Postgres, JS/Python clients, Row Level Security available |
| Auth | API tokens + JWT | Machine-to-machine (tokens) and user sessions (JWT) |

## Why This Exists Separately

This engine exists as standalone infrastructure — not embedded in any single product — to enforce conceptual boundaries:

- **"Is this an outbound feature or a product-specific feature?"** — forced by the separation
- **Multiple products can share it** — Outbound Solutions, ColdEmail.com, staffing tools, RA
- **Provider swaps don't ripple** — swap Smartlead for Instantly, only the provider module changes
- **Each product is a tenant** — not a fork, not a separate deployment

## Multi-Tenancy Model

### Three Tiers

```
Tier 1: Organization    — Your business (RA, Outbound Solutions)
Tier 2: Company          — Client company under that org
Tier 3: User             — Person at that company
```

### Query Scoping

Every database query chains down the tenant hierarchy:

```python
# Org-level: "show me all companies in my org"
.eq("org_id", auth.org_id)

# Company-level: "show me campaigns for this company"
.eq("org_id", auth.org_id).eq("company_id", company_id)
```

Company-level resources validate the company belongs to the org before any operation.

## Provider Abstraction

### Design Principle

The company/user layer never sees provider names. They interact with **capabilities**.

### Layer Diagram

```
┌─────────────────────────────────────────────────┐
│  Frontend Product (Outbound Solutions, etc.)     │
├─────────────────────────────────────────────────┤
│  Outbound Engine X API                          │
│  ┌────────────────────────────────────────────┐ │
│  │  Capability Router                         │ │
│  │  "email_outreach" → which provider?        │ │
│  └──────┬──────────────────┬──────────────────┘ │
│         │                  │                    │
│  ┌──────▼──────┐   ┌──────▼──────┐             │
│  │  Smartlead  │   │  HeyReach   │             │
│  │  Provider   │   │  Provider   │             │
│  └──────┬──────┘   └──────┬──────┘             │
│         │                  │                    │
├─────────▼──────────────────▼────────────────────┤
│  Smartlead API          HeyReach API            │
└─────────────────────────────────────────────────┘
```

### Adding a New Provider

1. Create new module in `src/providers/newprovider/`
2. Implement the provider interface (create campaign, add leads, etc.)
3. Add provider record to `providers` table
4. Map it to the relevant capability
5. Companies entitled to that capability can now use the new provider
6. No changes to routers, auth, or other providers

### Entitlement Flow

```
Company pays for "email outreach"
  → company_entitlements row created (capability=email_outreach, provider=smartlead)
  → status = "entitled"

Company provides Smartlead API key or admin connects it
  → provider_config updated with credentials
  → status = "connected"

API call comes in for "create campaign"
  → look up company's entitlement for email_outreach
  → resolve to smartlead provider
  → call smartlead provider module
  → store campaign record with provider reference
```

## Auth Model

### Two Auth Methods

**API Tokens** (machine-to-machine):
- Hashed and stored in `api_tokens` table
- Looked up on each request, returns org_id + user_id
- Used by: automation systems, n8n, external integrations

**JWT Sessions** (user login):
- Issued on login, contains org_id + user_id + company_id
- Validated without DB call (signature check only)
- Used by: frontend products, user-facing interfaces

### AuthContext

Both methods produce the same AuthContext object, which is injected into every endpoint via FastAPI dependency:

```python
async def get_current_auth(authorization: str = Header(None)) -> AuthContext:
    # Try JWT first (no DB call)
    # Fall back to API token (DB lookup)
    # Return AuthContext with org_id, user_id, company_id
```

### What AuthContext Carries

| Field | Source | Purpose |
|-------|--------|---------|
| `org_id` | Token/JWT | Tenant isolation — scopes every query |
| `user_id` | Token/JWT | Audit trail, ownership |
| `role` | User record | Canonical RBAC role used for policy checks |
| `permissions[]` | Derived from role | Explicit capability checks used by endpoint guards and frontend feature gating |
| `company_id` | Token/JWT + user record | Company-level scoping for company roles |
| `auth_method` | Derived | "api_token" or "session" |

### RBAC Model (Phase 1)

- `org_admin`: org-wide management and cross-company visibility.
- `company_admin`: company-scoped operational management.
- `company_member`: company-scoped day-to-day operator with read access and restricted write access.

Role names are canonicalized at auth boundaries. Legacy role inputs are accepted during transition:

- `admin` -> `org_admin`
- `user` -> `company_member`

Authorization is permission-first (role bundles), not string-comparison-first:

- `campaigns.read`, `campaigns.write`
- `inboxes.read`, `inboxes.write`
- `analytics.read`
- `org.manage_users`, `org.manage_companies`, `org.manage_entitlements`

`GET /api/auth/me` includes both canonical `role` and `permissions[]` so frontend surfaces can hide/disable actions (for example, campaign creation for users without `campaigns.write`).

## Modal + Railway Pattern

```
User Request
  → Railway (routing, SSL, domain)
    → Modal (compute, FastAPI app)
      → Supabase (data)
      → Smartlead/HeyReach APIs (providers)
```

- Modal app: `outbound-engine-x`
- All FastAPI endpoints are functions within the single Modal app
- Railway proxies to the Modal web endpoint URL
- Same pattern as `service-engine-x`

## Error Handling

- 401: Missing or invalid auth token
- 403: Valid token but insufficient permissions (e.g., user trying org-admin action)
- 404: Resource not found OR resource belongs to different org (same response to prevent enumeration)
- 400: Invalid request payload
- 502: Provider API error (Smartlead/HeyReach down or returned error)