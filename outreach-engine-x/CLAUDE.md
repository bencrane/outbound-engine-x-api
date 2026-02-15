# CLAUDE.md — Outbound Engine X

## What This Is

Multi-tenant outbound infrastructure engine. Abstracts over email (Smartlead) and LinkedIn (HeyReach) outreach providers. Any frontend product (Outbound Solutions, ColdEmail.com, staffing tools, etc.) can plug into this API to give their users outbound capabilities — without those users ever knowing the underlying provider.

This is part of the `-engine-x` family (alongside `service-engine-x`, `crm-engine-x`). Same architectural philosophy: standalone multi-tenant SaaS, independent DB, independent deployment.

## Stack

- **API**: FastAPI (Python)
- **Compute**: Modal
- **Routing/Deployment**: Railway
- **Database**: Supabase (Postgres)
- **Auth**: API tokens + JWT sessions (AuthContext pattern)

## Three-Tier Tenant Model

```
Organization (partner org — e.g., Revenue Activation, Outbound Solutions)
  └── Company (client company under that partner)
       └── User (person at that company who logs in and does things)
```

- `org_id` scopes everything. Every query, every table.
- Companies cannot see other companies under the same org.
- Orgs cannot see other orgs.
- Users belong to a company and inherit its scope.

## Provider Abstraction

Companies see **capabilities** (email_outreach, linkedin_outreach), not providers.
The system maps capabilities to **providers** (smartlead, instantly, heyreach) internally.

```
Capability: email_outreach    → Provider: smartlead (or instantly)
Capability: linkedin_outreach → Provider: heyreach
```

Entitlement model per company:
- **entitled** — paid for, available
- **connected** — credentials provided, active
- **disconnected** — was connected, currently not

## Project Structure

```
outbound-engine-x/
├── CLAUDE.md              ← You are here
├── pyproject.toml
├── .env                   ← Never committed (see .env.example)
├── .env.example
├── src/
│   ├── main.py            ← FastAPI app + Modal entrypoint
│   ├── config.py          ← Pydantic Settings, env vars
│   ├── auth/              ← AuthContext, token validation, dependencies
│   ├── models/            ← Pydantic models (request/response schemas)
│   ├── routers/           ← FastAPI routers (org, company, user, campaigns, etc.)
│   └── providers/         ← Provider-specific API clients
│       ├── smartlead/
│       └── heyreach/
└── docs/
    ├── SCHEMA.md          ← DB schema documentation
    └── ARCHITECTURE.md    ← Stack decisions, provider pattern, auth model
```

## Database Conventions

- Every tenant-scoped table has `org_id UUID NOT NULL REFERENCES organizations(id)`
- Child tables denormalize `org_id` for query efficiency (no joins to filter by tenant)
- All queries filter by `org_id` — no exceptions
- Soft delete via `deleted_at` timestamp
- All tables have `created_at` and `updated_at`
- UUIDs for all primary keys

## Auth Pattern

AuthContext carries tenant identity through every request:

```python
@dataclass
class AuthContext:
    org_id: str
    user_id: str
    company_id: str | None = None
    auth_method: str = "api_token"  # "api_token" or "session"
```

- API tokens: looked up in `api_tokens` table, return org_id + user_id
- JWT sessions: org_id embedded in token payload
- `org_id` is NEVER accepted from request body — always from auth context

## Key Rules

- Never expose provider details (smartlead, heyreach) to the client/company layer
- Never allow `org_id` in request payloads — always derived from auth
- Every SELECT/UPDATE/DELETE must include `.eq("org_id", auth.org_id)`
- Every INSERT must set `org_id` from `auth.org_id`
- Related resource IDs must be validated within the same org before use
- Error messages must not reveal existence of other orgs' data

## Build Phases

### Phase 1 (Current)
- Organizations, Companies, Users — full CRUD with tenant isolation
- Auth (API tokens + JWT)
- Provider entitlements table
- DB schema + migrations

### Phase 2
- Smartlead integration endpoints (campaigns, sequences, leads, email accounts)
- Webhook ingestion from Smartlead

### Phase 3
- HeyReach integration endpoints (campaigns, leads, LinkedIn accounts)
- Webhook ingestion from HeyReach

## Workflow

- **"commit"** means: stage, commit, and push to GitHub. Always push.

## Environment Variables

See `.env.example` for required values. Never commit `.env`.