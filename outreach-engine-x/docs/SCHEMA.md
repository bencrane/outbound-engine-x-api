# Database Schema — Outbound Engine X

## Overview

Three-tier multi-tenant model: Organization → Company → User.
Provider-agnostic outbound infrastructure with capability-based entitlements.

---

## Core Tables (Phase 1)

### organizations

The top-level tenant. Represents a partner business (e.g., Revenue Activation, Outbound Solutions).

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PK, DEFAULT gen_random_uuid() | |
| `name` | VARCHAR(255) | NOT NULL | Organization name |
| `slug` | VARCHAR(100) | UNIQUE, NOT NULL | URL-safe identifier |
| `created_at` | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() | |
| `updated_at` | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() | |
| `deleted_at` | TIMESTAMPTZ | NULLABLE | Soft delete |

---

### companies

A client company under an organization. This is who the org sold outbound services to.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PK, DEFAULT gen_random_uuid() | |
| `org_id` | UUID | NOT NULL, FK → organizations(id) | Tenant scope |
| `name` | VARCHAR(255) | NOT NULL | Company name |
| `domain` | VARCHAR(255) | NULLABLE | Company website domain |
| `status` | VARCHAR(20) | NOT NULL, DEFAULT 'active' | active, inactive, churned |
| `created_at` | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() | |
| `updated_at` | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() | |
| `deleted_at` | TIMESTAMPTZ | NULLABLE | Soft delete |

**Indexes:** `idx_companies_org_id`

---

### users

A person who can log in. Belongs to a company (client user) or directly to an org (admin/team).

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PK, DEFAULT gen_random_uuid() | |
| `org_id` | UUID | NOT NULL, FK → organizations(id) | Tenant scope |
| `company_id` | UUID | NULLABLE, FK → companies(id) | NULL = org-level admin/team |
| `email` | VARCHAR(255) | NOT NULL | Login email |
| `password_hash` | VARCHAR(255) | NOT NULL | Hashed password |
| `name_first` | VARCHAR(100) | NULLABLE | |
| `name_last` | VARCHAR(100) | NULLABLE | |
| `role` | VARCHAR(20) | NOT NULL, DEFAULT 'user' | owner, admin, user |
| `created_at` | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() | |
| `updated_at` | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() | |
| `deleted_at` | TIMESTAMPTZ | NULLABLE | Soft delete |

**Indexes:** `idx_users_org_id`, `idx_users_company_id`, `UNIQUE(org_id, email)`

---

### api_tokens

Machine-to-machine authentication tokens.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PK, DEFAULT gen_random_uuid() | |
| `org_id` | UUID | NOT NULL, FK → organizations(id) | Tenant scope |
| `user_id` | UUID | NOT NULL, FK → users(id) | Token owner |
| `token_hash` | VARCHAR(255) | NOT NULL, UNIQUE | SHA-256 hash of token |
| `name` | VARCHAR(100) | NULLABLE | Descriptive label |
| `expires_at` | TIMESTAMPTZ | NULLABLE | NULL = never expires |
| `last_used_at` | TIMESTAMPTZ | NULLABLE | |
| `created_at` | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() | |

**Indexes:** `idx_api_tokens_token_hash`, `idx_api_tokens_org_id`

---

### capabilities

Defines what outbound capabilities exist in the system.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PK, DEFAULT gen_random_uuid() | |
| `slug` | VARCHAR(50) | UNIQUE, NOT NULL | e.g., email_outreach, linkedin_outreach |
| `name` | VARCHAR(100) | NOT NULL | Display name |
| `created_at` | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() | |

**Seed data:**
- `email_outreach` — "Email Outreach"
- `linkedin_outreach` — "LinkedIn Outreach"

---

### providers

Defines which providers fulfill capabilities. System-level, not tenant-scoped.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PK, DEFAULT gen_random_uuid() | |
| `capability_id` | UUID | NOT NULL, FK → capabilities(id) | Which capability this fulfills |
| `slug` | VARCHAR(50) | UNIQUE, NOT NULL | e.g., smartlead, heyreach, instantly |
| `name` | VARCHAR(100) | NOT NULL | Display name |
| `created_at` | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() | |

**Seed data:**
- `smartlead` → fulfills `email_outreach`
- `instantly` → fulfills `email_outreach`
- `heyreach` → fulfills `linkedin_outreach`

---

### company_entitlements

What capabilities a company has paid for, and which provider fulfills it.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PK, DEFAULT gen_random_uuid() | |
| `org_id` | UUID | NOT NULL, FK → organizations(id) | Tenant scope |
| `company_id` | UUID | NOT NULL, FK → companies(id) | Which company |
| `capability_id` | UUID | NOT NULL, FK → capabilities(id) | What they're entitled to |
| `provider_id` | UUID | NOT NULL, FK → providers(id) | Which provider fulfills it |
| `status` | VARCHAR(20) | NOT NULL, DEFAULT 'entitled' | entitled, connected, disconnected |
| `provider_config` | JSONB | NULLABLE | Provider-specific credentials/config |
| `created_at` | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() | |
| `updated_at` | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() | |

**Indexes:** `idx_company_entitlements_org_id`, `idx_company_entitlements_company_id`
**Unique:** `(company_id, capability_id)` — one entitlement per capability per company

---

## Relationship Diagram

```
organizations
  │
  ├── companies
  │     ├── users (company_id set)
  │     └── company_entitlements
  │           ├── → capabilities (email_outreach, linkedin_outreach)
  │           └── → providers (smartlead, heyreach, instantly)
  │
  ├── users (company_id NULL = org admin/team)
  │
  └── api_tokens
```

---

## Provider-Specific Tables (Phase 2+)

These tables will be added when Smartlead/HeyReach integration is built. They will all carry `org_id` and `company_id` for tenant scoping.

Planned tables include:
- `campaigns` — local campaign records mapping to provider campaign IDs
- `sequences` — email sequence steps
- `leads` — contacts added to campaigns
- `email_accounts` — sending accounts/inboxes
- `campaign_analytics` — synced stats
- `webhook_events` — inbound webhook payloads

Detailed schemas will be added to this document in Phase 2.

---

## Cascade Rules

| Parent | Child | On Delete |
|--------|-------|-----------|
| organizations | companies | CASCADE |
| organizations | users | CASCADE |
| organizations | api_tokens | CASCADE |
| companies | users | CASCADE |
| companies | company_entitlements | CASCADE |

---

## Conventions

- All primary keys are UUID v4 via `gen_random_uuid()`
- All tenant-scoped tables have `org_id` with index
- Soft delete via `deleted_at` — all queries must filter `.is_("deleted_at", "null")`
- Timestamps are `TIMESTAMPTZ`, always UTC
- `updated_at` must be set on every update