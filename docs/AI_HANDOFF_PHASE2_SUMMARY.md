# AI Handoff Summary: Phase 1 Hardening + Phase 2 Email Foundation

## Purpose

This document is a comprehensive handoff for future AI instances and engineers.  
It captures what was built, what was migrated, what is currently live in code, and what remains.

---

## Executive Summary

The codebase progressed from Phase 1 tenant/auth hardening into a production-oriented Phase 2 email foundation (Smartlead-backed, provider-hidden):

- Tenant auth boundaries were hardened (`org_id` isolation + role guardrails).
- Internal provisioning for email capability was added.
- Local persistence was added for inboxes, campaigns, sequences, leads, and messages.
- Campaign lifecycle endpoints were added (create, status, sequence, leads, replies/messages).
- Smartlead webhook ingestion with idempotency and optional signature verification was added.
- Focused test suites were added and passing.

Latest checkpoint commit on `main`: `c7ce61f`.

---

## Key Architectural Decisions (Implemented)

1. **Local DB is source-of-truth for product views**
- Provider APIs are execution backends.
- App UI should read from local tables first.
- Webhooks + sync endpoints keep local state current.

2. **Provider abstraction is preserved**
- Frontend uses capability-level APIs (`campaigns`, `inboxes`, etc.).
- Provider details are resolved internally via entitlement/provider mapping.

3. **No tenant-provided org scope**
- `org_id` never accepted from payloads.
- Always derived from auth context.

4. **Provisioning is explicit, not login-triggered**
- Email outreach setup is internal/super-admin-driven.
- Login does not cause provider-side side effects.

5. **Tenant token management policy**
- Tenant `/api/auth/tokens*` is disabled (`403`).
- API token creation is super-admin-only.

---

## Current Router Surface

### Super Admin (`/api/super-admin`)
- Login/me
- Org CRUD
- Org-scoped user/company listing and creation
- Org-scoped user soft delete
- Org API token creation
- Org provider config set
- Capability/provider lookup

### Tenant Foundation
- `/api/organizations`: list/get/update (same-org only)
- `/api/companies`: CRUD (admin-only)
- `/api/users`: CRUD (admin-only)
- `/api/entitlements`: CRUD (admin-only)
- `/api/auth/login`
- `/api/auth/me`
- `/api/auth/tokens*` => intentionally returns `403`

### Internal Provisioning (`/api/internal/provisioning`)
- `POST /email-outreach/{company_id}`
- `GET /email-outreach/{company_id}/status`
- `POST /email-outreach/{company_id}/sync-inboxes`

### Inboxes (`/api/inboxes`)
- `GET /` (company-scoped users see own company; org-level callers must be admin and supply `company_id`)

### Campaigns (`/api/campaigns`)
- `POST /`
- `GET /`
- `GET /{campaign_id}`
- `POST /{campaign_id}/status`
- `GET /{campaign_id}/sequence`
- `POST /{campaign_id}/sequence`
- `POST /{campaign_id}/leads`
- `GET /{campaign_id}/leads`
- `POST /{campaign_id}/leads/{lead_id}/pause`
- `POST /{campaign_id}/leads/{lead_id}/resume`
- `POST /{campaign_id}/leads/{lead_id}/unsubscribe`
- `GET /{campaign_id}/replies`
- `GET /{campaign_id}/leads/{lead_id}/messages`

### Webhooks (`/api/webhooks`)
- `POST /smartlead`
  - idempotent event persistence (`webhook_events`)
  - optional HMAC verification (if `smartlead_webhook_secret` set)
  - campaign/lead/message local updates when matching local mappings exist

---

## Database Migrations Added

Base:
- `001_phase1_tables.sql`
- `002_super_admins.sql`
- `003_org_provider_configs.sql`

Hardening:
- `004_phase1_constraint_hardening.sql`

Phase 2 foundation:
- `005_company_inboxes.sql`
- `006_company_campaigns.sql` (includes `UNIQUE (id, org_id)` to support composite FKs)
- `007_campaign_sequences.sql`
- `008_company_campaign_leads.sql`
- `009_company_campaign_messages.sql`
- `010_webhook_events.sql`

### Important dependency note

`007+` depend on composite uniqueness/FKs from `006`.  
If replaying in a fresh environment, apply in strict order `001 -> 010`.

---

## New/Updated Tables (Conceptual)

- `company_inboxes`: provider inbox mapping per company
- `company_campaigns`: provider campaign mapping + local campaign metadata
- `company_campaign_sequences`: versioned sequence snapshots
- `company_campaign_leads`: provider lead mapping + local lead state
- `company_campaign_messages`: local message/reply snapshots
- `webhook_events`: idempotency and audit for webhooks

---

## Smartlead Provider Client Coverage

`src/providers/smartlead/client.py` currently includes:

- connectivity/auth check
- inbox list
- campaign create/update status
- sequence get/save
- campaign lead add/list/pause/resume/unsubscribe
- campaign replies fetch
- lead message history fetch

It uses endpoint fallbacks for compatibility across Smartlead variants and raises explicit provider errors on mismatch/failure.

---

## Tests Added

- `tests/test_phase1_provisioning_endpoints.py`
- `tests/test_inboxes_endpoint.py`
- `tests/test_campaigns_endpoints.py`
- `tests/test_webhooks_endpoint.py`
- Authorization matrices (current canonical set):
  - `tests/test_analytics_authorization_matrix.py`
  - `tests/test_internal_reconciliation_authorization_matrix.py`
  - `tests/test_webhooks_authorization_matrix.py`
  - `tests/test_internal_provisioning_authorization_matrix.py`

Current suite status has expanded beyond the original 19-test checkpoint; use the live repo test set as source of truth.

Run command:

```bash
source .venv/bin/activate
PYTHONPATH=. pytest -q tests/test_campaigns_endpoints.py tests/test_linkedin_campaigns_endpoints.py tests/test_analytics_authorization_matrix.py tests/test_internal_reconciliation_authorization_matrix.py tests/test_webhooks_authorization_matrix.py tests/test_internal_provisioning_authorization_matrix.py
```

---

## Deployment / Checkpoints

Recent commits:
- `9a00a6d` Build phase 2 email foundation with provisioning, inbox sync, campaigns, and sequences.
- `c7ce61f` Extend campaign execution with leads lifecycle, message history, and webhook ingestion.

Both were pushed to `main` to trigger Railway auto-deploy.

---

## Operational Notes

1. **Supabase migrations applied**
- `005` through `010` have been applied to the target Supabase project during this session.

2. **Webhook signature**
- Optional secret: `smartlead_webhook_secret`.
- If set, requests must include `X-Smartlead-Signature` (HMAC SHA-256 over raw body).

3. **Pydantic settings config**
- `src/config.py` now uses `SettingsConfigDict`/`model_config` (Pydantic v2-compatible).
- No action required for the prior class-based config deprecation note in this handoff context.

---

## Known Gaps / Next Work

1. **Endpoint contract hardening**
- Standardize provider response normalization where Smartlead payloads vary.
- Add stricter schema validation for webhook payloads.

2. **Webhook expansion**
- Broaden event-type mapping coverage and ensure all relevant statuses are synchronized.
- Add dead-letter / retry mechanism for processing failures.

3. **Analytics endpoints**
- Expose campaign-level analytics from local + provider sources.

4. **Docs completion**
- Ensure `docs/SUPER_ADMIN_API.md` and `docs/API.md` stay aligned with current code after each slice.

5. **HeyReach path**
- Add LinkedIn campaign capability path mirroring email architecture.

---

## Recommended Next Slice

If continuing Phase 2 immediately, prioritize:

1. webhook event taxonomy + mapping hardening  
2. analytics read endpoints  
3. docs sync + one more checkpoint commit

This keeps the current email foundation stable while increasing production reliability.
