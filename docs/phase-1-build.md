# Phase 1 Build Instructions

Read `CLAUDE.md` for project context and `docs/SCHEMA.md` for the complete database spec before starting.

---

## Step 1: Create Database Tables

Connect to the database using `DATABASE_URL` from `.env`.

Create tables in this order (foreign key dependencies matter):

1. `organizations`
2. `companies`
3. `users`
4. `api_tokens`
5. `capabilities`
6. `providers`
7. `company_entitlements`

All column definitions, types, constraints, indexes, and cascade rules are in `docs/SCHEMA.md`. Follow it exactly.

**Seed data after table creation:**

Capabilities:
- `email_outreach` — "Email Outreach"
- `linkedin_outreach` — "LinkedIn Outreach"

Providers:
- `smartlead` → fulfills `email_outreach`
- `instantly` → fulfills `email_outreach`
- `heyreach` → fulfills `linkedin_outreach`

---

## Step 2: Auth

Build `src/auth/` with two files:

### `src/auth/context.py`

```python
@dataclass
class AuthContext:
    org_id: str
    user_id: str
    company_id: str | None = None
    token_id: str | None = None
    auth_method: str = "api_token"  # "api_token" or "session"
```

### `src/auth/dependencies.py`

Three dependency functions:

- `get_current_auth()` — dual auth. Tries JWT first (no DB call), falls back to API token (DB lookup). Returns AuthContext.
- `get_current_org()` — API token only. For machine-to-machine calls.
- `get_current_user()` — JWT session only. For user-facing endpoints.

**API token validation:**
- Extract bearer token from Authorization header
- SHA-256 hash it
- Look up hash in `api_tokens` table
- Check expiration (`expires_at`)
- Return AuthContext with org_id, user_id from token record
- Update `last_used_at` on the token

**JWT validation:**
- Extract bearer token from Authorization header
- Decode using `JWT_SECRET` and `JWT_ALGORITHM` from config
- Verify `type` == `"session"`
- Extract `sub` (user_id), `org_id`, `company_id` from payload
- Return AuthContext

### `src/auth/jwt.py`

- `create_access_token(user_id, org_id, company_id)` — creates a signed JWT with expiration
- `decode_access_token(token)` — decodes and validates

Use `python-jose` for JWT operations. Get `JWT_SECRET`, `JWT_ALGORITHM`, `JWT_EXPIRATION_MINUTES` from config.

### `src/config.py`

Pydantic Settings class loading from `.env`:

```python
class Settings(BaseSettings):
    database_url: str
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expiration_minutes: int = 60

    class Config:
        env_file = ".env"
```

---

## Step 3: Database Client

Create `src/db.py` — initialize Supabase client using config values. This is what all routers import to query the database.

---

## Step 4: CRUD Routers

Build routers in `src/routers/`. Every endpoint uses `auth: AuthContext = Depends(get_current_auth)`.

### `src/routers/organizations.py`

Prefix: `/api/organizations`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | List orgs (admin only — the authenticated user's org) |
| GET | `/{org_id}` | Get org by ID (must match auth.org_id) |
| PUT | `/{org_id}` | Update org |

Note: Org creation is a separate bootstrapping concern — not a standard API endpoint. For now, orgs will be created directly in the database or via a seed script.

### `src/routers/companies.py`

Prefix: `/api/companies`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | List companies in org |
| POST | `/` | Create company |
| GET | `/{company_id}` | Get company |
| PUT | `/{company_id}` | Update company |
| DELETE | `/{company_id}` | Soft delete company |

All queries scoped by `auth.org_id`. Create sets `org_id` from auth context. Retrieve/update/delete verify both `id` and `org_id` match.

### `src/routers/users.py`

Prefix: `/api/users`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | List users in org (optional `company_id` filter) |
| POST | `/` | Create user |
| GET | `/{user_id}` | Get user |
| PUT | `/{user_id}` | Update user |
| DELETE | `/{user_id}` | Soft delete user |

Password must be hashed with `passlib[bcrypt]` on create/update. Never return `password_hash` in responses.

### `src/routers/entitlements.py`

Prefix: `/api/entitlements`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | List entitlements (optional `company_id` filter) |
| POST | `/` | Create entitlement for a company |
| GET | `/{entitlement_id}` | Get entitlement |
| PUT | `/{entitlement_id}` | Update entitlement (status, provider_config) |
| DELETE | `/{entitlement_id}` | Delete entitlement |

Validate that `company_id`, `capability_id`, and `provider_id` all exist and belong to the correct org before creating.

### `src/routers/auth_routes.py`

Prefix: `/api/auth`

| Method | Path | Description |
|--------|------|-------------|
| POST | `/login` | Accept email + password, verify, return JWT |
| POST | `/tokens` | Create new API token, return the raw token (only time it's visible) |
| GET | `/tokens` | List API tokens for the org (metadata only, not the token value) |
| DELETE | `/tokens/{token_id}` | Revoke an API token |
| GET | `/me` | Return current user info from AuthContext |

---

## Step 5: Pydantic Models

Create request/response models in `src/models/`. Every router should have clearly defined input and output schemas. Never expose `password_hash`, `deleted_at`, or `org_id` in responses unless intentionally needed.

---

## Step 6: Wire Into Main App

Update `src/main.py` to import and register all routers:

```python
from src.routers import organizations, companies, users, entitlements, auth_routes

app.include_router(organizations.router)
app.include_router(companies.router)
app.include_router(users.router)
app.include_router(entitlements.router)
app.include_router(auth_routes.router)
```

`/health` endpoint must continue to work.

---

## Step 7: Verify

After building, confirm:
- [ ] All tables exist in Supabase with correct columns, indexes, and constraints
- [ ] Seed data exists in capabilities and providers tables
- [ ] `/health` returns 200
- [ ] Can create an API token (directly in DB for bootstrapping)
- [ ] Auth dependency correctly validates tokens and returns AuthContext
- [ ] Company CRUD works with org_id scoping
- [ ] User CRUD works with org_id scoping
- [ ] Entitlement CRUD validates related resources within same org
- [ ] No endpoint accepts org_id from request body
- [ ] No endpoint returns password_hash
- [ ] Soft-deleted records are excluded from all queries

---

## Key Rules (from CLAUDE.md)

- `org_id` NEVER from request body — always from AuthContext
- Every SELECT/UPDATE/DELETE includes `.eq("org_id", auth.org_id)`
- Every INSERT sets `org_id` from `auth.org_id`
- Related resource IDs validated within same org
- Error messages never reveal other orgs' data
- Soft delete via `deleted_at`, all queries filter `.is_("deleted_at", "null")`