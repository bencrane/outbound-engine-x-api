# API Reference — Outbound Engine X

## Authentication

### Super-Admin Auth

Super-admins use JWT tokens obtained via login.

```
POST /api/super-admin/login
Content-Type: application/json

{ "email": "...", "password": "..." }
```

Response:
```json
{ "access_token": "eyJ...", "token_type": "bearer" }
```

Use in subsequent requests:
```
Authorization: Bearer <access_token>
```

### Org-Level Auth (API Tokens)

API tokens are created by super-admins and scoped to an org.

```
Authorization: Bearer <api_token>
```

API tokens automatically scope all queries to their org.

---

## Super-Admin Endpoints

All require `Authorization: Bearer <super-admin-token>`.

### Auth

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/super-admin/login` | Login, returns JWT |
| GET | `/api/super-admin/me` | Current super-admin info |

### System Lookups

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/super-admin/capabilities` | List capabilities (email_outreach, linkedin_outreach) |
| GET | `/api/super-admin/providers` | List providers (smartlead, heyreach, etc.) |

### Organizations

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/super-admin/organizations` | Create org |
| GET | `/api/super-admin/organizations` | List all orgs |
| GET | `/api/super-admin/organizations/{org_id}` | Get org |
| PUT | `/api/super-admin/organizations/{org_id}` | Update org |
| DELETE | `/api/super-admin/organizations/{org_id}` | Soft delete org |

**Create Org Request:**
```json
{ "name": "Acme Corp", "slug": "acme-corp" }
```

**Org Response:**
```json
{
  "id": "uuid",
  "name": "Acme Corp",
  "slug": "acme-corp",
  "provider_configs": { "heyreach": { "api_key": "..." } },
  "created_at": "...",
  "updated_at": "..."
}
```

### Org-Scoped Operations

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/super-admin/organizations/{org_id}/users` | Create user in org |
| GET | `/api/super-admin/organizations/{org_id}/users` | List users in org |
| GET | `/api/super-admin/organizations/{org_id}/companies` | List companies in org |
| POST | `/api/super-admin/organizations/{org_id}/api-tokens` | Create API token |
| PUT | `/api/super-admin/organizations/{org_id}/provider-config` | Set provider API key |

**Create User Request:**
```json
{
  "email": "admin@acme.com",
  "password": "...",
  "name_first": "Admin",
  "name_last": "User",
  "role": "admin"
}
```

**Create API Token Request:**
```json
{ "user_id": "<user_id>", "name": "Primary Token" }
```

**Set Provider Config Request:**
```json
{ "provider_slug": "heyreach", "config": { "api_key": "..." } }
```

---

## Tenant Endpoints

All require `Authorization: Bearer <api_token>` (org-scoped).

### Organizations

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/organizations/` | List orgs (returns only authenticated org) |
| GET | `/api/organizations/{org_id}` | Get org (must match auth) |
| PUT | `/api/organizations/{org_id}` | Update org |

### Companies

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/companies/` | Create company |
| GET | `/api/companies/` | List companies |
| GET | `/api/companies/{id}` | Get company |
| PUT | `/api/companies/{id}` | Update company |
| DELETE | `/api/companies/{id}` | Soft delete company |

**Create Company Request:**
```json
{ "name": "Client Corp", "domain": "client.com" }
```

### Users

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/users/` | Create user |
| GET | `/api/users/` | List users (optional `?company_id=`) |
| GET | `/api/users/{id}` | Get user |
| PUT | `/api/users/{id}` | Update user |
| DELETE | `/api/users/{id}` | Soft delete user |

### Entitlements

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/entitlements/` | Create entitlement |
| GET | `/api/entitlements/` | List entitlements (optional `?company_id=`) |
| GET | `/api/entitlements/{id}` | Get entitlement |
| PUT | `/api/entitlements/{id}` | Update entitlement |
| DELETE | `/api/entitlements/{id}` | Delete entitlement |

**Create Entitlement Request:**
```json
{
  "company_id": "<company_id>",
  "capability_id": "<capability_id>",
  "provider_id": "<provider_id>"
}
```

### Auth

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/auth/login` | User login, returns JWT |
| GET | `/api/auth/me` | Current auth context |
| POST | `/api/auth/tokens` | Create API token |
| GET | `/api/auth/tokens` | List API tokens |
| DELETE | `/api/auth/tokens/{id}` | Revoke token |

---

## Current IDs

Fetch dynamically via `/api/super-admin/capabilities` and `/api/super-admin/providers`.

### Capabilities

| Slug | ID |
|------|-----|
| `email_outreach` | `9032dd88-dcd0-4d36-8b36-b0d6b15a605c` |
| `linkedin_outreach` | `21863645-512d-4089-aff5-c7c46954a491` |

### Providers

| Slug | Capability | ID |
|------|------------|-----|
| `smartlead` | email_outreach | `1da740f2-fdce-42b1-997b-f360563f57a8` |
| `instantly` | email_outreach | `966d0e68-0f34-48c7-bfc0-699a7fc67fbd` |
| `heyreach` | linkedin_outreach | `5e22d2e8-98b4-4f90-8aa1-3b2e680bc34e` |
