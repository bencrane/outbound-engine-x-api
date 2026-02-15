# Super Admin API

Base URL: `https://api.outboundengine.dev` (production) or `http://localhost:8000` (local)

All endpoints (except login) require: `Authorization: Bearer <super_admin_jwt>`

---

## Authentication

### Login

```
POST /api/super-admin/login
```

**Request:**
```json
{
  "email": "admin@example.com",
  "password": "your-password"
}
```

**Response:**
```json
{
  "access_token": "eyJ...",
  "token_type": "bearer"
}
```

### Get Current User

```
GET /api/super-admin/me
```

**Response:**
```json
{
  "super_admin_id": "uuid",
  "email": "admin@example.com"
}
```

---

## Organizations

### List Organizations

```
GET /api/super-admin/organizations
```

**Response:**
```json
[
  {
    "id": "uuid",
    "name": "Acme Corp",
    "slug": "acme-corp",
    "provider_configs": {},
    "created_at": "2026-02-15T20:50:32Z",
    "updated_at": "2026-02-15T20:50:32Z"
  }
]
```

### Create Organization

```
POST /api/super-admin/organizations
```

**Request:**
```json
{
  "name": "Acme Corp",
  "slug": "acme-corp"
}
```

**Response:** Same as org object above.

### Get Organization

```
GET /api/super-admin/organizations/{org_id}
```

### Update Organization

```
PUT /api/super-admin/organizations/{org_id}
```

**Request:**
```json
{
  "name": "New Name",
  "slug": "new-slug"
}
```

### Delete Organization (soft delete)

```
DELETE /api/super-admin/organizations/{org_id}
```

**Response:** `204 No Content`

---

## Companies (under an Org)

### List Companies

```
GET /api/super-admin/organizations/{org_id}/companies
```

**Response:**
```json
[
  {
    "id": "uuid",
    "name": "Sales Team",
    "domain": "sales.acme.com",
    "status": "active",
    "created_at": "2026-02-15T20:50:32Z",
    "updated_at": "2026-02-15T20:50:32Z"
  }
]
```

### Create Company

```
POST /api/super-admin/organizations/{org_id}/companies
```

**Request:**
```json
{
  "name": "Sales Team",
  "domain": "sales.acme.com"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| name | string | Yes | Company name |
| domain | string | No | Company domain |

**Response:** Same as company object above.

### Delete Company (soft delete)

```
DELETE /api/super-admin/organizations/{org_id}/companies/{company_id}
```

**Response:** `204 No Content`

---

## Users (under an Org)

### List Users

```
GET /api/super-admin/organizations/{org_id}/users
```

**Response:**
```json
[
  {
    "id": "uuid",
    "email": "john@acme.com",
    "company_id": "uuid or null",
    "name_first": "John",
    "name_last": "Doe",
    "role": "admin",
    "created_at": "2026-02-15T20:50:32Z",
    "updated_at": "2026-02-15T20:50:32Z"
  }
]
```

### Create User

```
POST /api/super-admin/organizations/{org_id}/users
```

**Request:**
```json
{
  "email": "john@acme.com",
  "password": "secure-password",
  "name_first": "John",
  "name_last": "Doe",
  "role": "admin"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| email | string | Yes | User email |
| password | string | Yes | User password |
| name_first | string | No | First name |
| name_last | string | No | Last name |
| role | string | No | `admin` or `user` (default: `admin`) |

**Response:** Same as user object above (without password).

### Delete User (soft delete)

```
DELETE /api/super-admin/organizations/{org_id}/users/{user_id}
```

**Response:** `204 No Content`

---

## API Tokens

### Create API Token (for an org user)

```
POST /api/super-admin/organizations/{org_id}/api-tokens
```

**Request:**
```json
{
  "user_id": "uuid",
  "name": "Primary Token",
  "expires_at": "2027-01-01T00:00:00Z"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| user_id | string | Yes | User ID (must belong to the org) |
| name | string | No | Token name/description |
| expires_at | string | No | ISO datetime for expiration |

**Response:**
```json
{
  "id": "uuid",
  "token": "the-raw-token-only-shown-once",
  "name": "Primary Token",
  "expires_at": "2027-01-01T00:00:00Z",
  "created_at": "2026-02-15T20:50:32Z"
}
```

---

## Provider Configuration

### Set Provider Config

```
PUT /api/super-admin/organizations/{org_id}/provider-config
```

**Request:**
```json
{
  "provider_slug": "smartlead",
  "config": {
    "api_key": "your-api-key"
  }
}
```

| Provider | Config Fields |
|----------|---------------|
| `smartlead` | `api_key` |
| `heyreach` | `api_key` |

**Response:**
```json
{
  "provider": "smartlead",
  "config_set": true
}
```

---

## System Lookups

### List Capabilities

```
GET /api/super-admin/capabilities
```

**Response:**
```json
[
  { "id": "uuid", "slug": "email_outreach", "name": "Email Outreach", "created_at": "..." }
]
```

### List Providers

```
GET /api/super-admin/providers
```

**Response:**
```json
[
  {
    "id": "uuid",
    "slug": "smartlead",
    "name": "Smartlead",
    "capability_id": "uuid",
    "capability_slug": "email_outreach",
    "created_at": "..."
  }
]
```

---

## Quick Reference

| Action | Method | Endpoint |
|--------|--------|----------|
| Login | POST | `/api/super-admin/login` |
| Me | GET | `/api/super-admin/me` |
| List orgs | GET | `/api/super-admin/organizations` |
| Create org | POST | `/api/super-admin/organizations` |
| Get org | GET | `/api/super-admin/organizations/{org_id}` |
| Update org | PUT | `/api/super-admin/organizations/{org_id}` |
| Delete org | DELETE | `/api/super-admin/organizations/{org_id}` |
| List companies | GET | `/api/super-admin/organizations/{org_id}/companies` |
| Create company | POST | `/api/super-admin/organizations/{org_id}/companies` |
| Delete company | DELETE | `/api/super-admin/organizations/{org_id}/companies/{company_id}` |
| List users | GET | `/api/super-admin/organizations/{org_id}/users` |
| Create user | POST | `/api/super-admin/organizations/{org_id}/users` |
| Delete user | DELETE | `/api/super-admin/organizations/{org_id}/users/{user_id}` |
| Create API token | POST | `/api/super-admin/organizations/{org_id}/api-tokens` |
| Set provider config | PUT | `/api/super-admin/organizations/{org_id}/provider-config` |
| List capabilities | GET | `/api/super-admin/capabilities` |
| List providers | GET | `/api/super-admin/providers` |
| List webhook events | GET | `/api/webhooks/events` |
| Replay webhook event | POST | `/api/webhooks/replay/{provider_slug}/{event_key}` |
| Bulk replay webhook events | POST | `/api/webhooks/replay-bulk` |
| Replay webhook events by query | POST | `/api/webhooks/replay-query` |
| Reconcile campaigns/leads | POST | `/api/internal/reconciliation/campaigns-leads` |
| Scheduled reconcile trigger | POST | `/api/internal/reconciliation/run-scheduled` |
