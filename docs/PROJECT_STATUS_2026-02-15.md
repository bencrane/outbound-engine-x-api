# Outbound Engine X API - Project Status (2026-02-15)

## Executive State

The project is in a strong Phase 2+ state: multi-tenant auth/authorization foundations are in place, Smartlead and HeyReach provider integrations are live, webhook ingestion + replay exists, and reconciliation infrastructure is deployed and running.

Current production status: stable for campaign/lead reconciliation across Smartlead and HeyReach, including fallback behavior for provider API shape differences. Smartlead message-history reconciliation is now implemented.
Campaign-level message sync observability is now implemented via `message_sync_status`, `last_message_sync_at`, and `last_message_sync_error`, with analytics exposure at `/api/analytics/message-sync-health`. Sequence-step attribution primitives are now in place via `sequence_step_number` capture on message writes and analytics exposure at `/api/analytics/campaigns/{campaign_id}/sequence-steps`.

## What Is Implemented

### Tenant/Auth Foundation
- Organization/company/user model with tenant isolation (`org_id` scoped queries).
- API token and JWT auth paths with shared auth context.
- Org-admin authorization hardening on tenant management routes.
- Super-admin controls for sensitive/internal operations.

### Provider Capability Layer
- Capability abstraction in place (`email_outreach`, `linkedin_outreach`).
- Smartlead integrated for email workflows.
- HeyReach integrated for LinkedIn workflows.
- Company entitlements enforce capability/provider access by tenant.

### Campaign Operations
- Email campaign routes (`/api/campaigns/*`) with sequences, leads, messages, analytics endpoints.
- LinkedIn campaign routes (`/api/linkedin/campaigns/*`) for create/list/get, action, leads, lead status, send message, metrics.
- Local persistence tables for campaigns, sequences, leads, and messages.
- Status/direction normalization layer for provider-agnostic API responses.

### Webhooks + Recovery Controls
- Smartlead and HeyReach webhook ingestion endpoints.
- Idempotent webhook storage with event key semantics.
- Super-admin replay controls:
  - single event replay
  - bulk replay
  - replay by query filters
- Durability metadata in `webhook_events` (status/replay_count/last_replay_at/last_error).

### Reconciliation + Scheduling
- Internal reconciliation endpoint for campaigns/leads with `dry_run` and `apply`.
- Smartlead message-history reconciliation into `company_campaign_messages` (campaign replies + lead thread pulls, bounded by request limits).
- Scheduler-facing endpoint (`/api/internal/reconciliation/run-scheduled`) protected by secret header.
- Observability baseline in place: request IDs (`X-Request-ID`), structured event logs, and in-process counters for webhook/reconciliation activity.
- Provider retry/backoff baseline in place for Smartlead + HeyReach HTTP clients (jittered exponential retries on 429/5xx and transient transport failures).
- HeyReach message-history strategy finalized:
  - default `webhook_only` mode for deterministic behavior
  - optional `pull_best_effort` mode via env config for lead-thread backfill when endpoint coverage exists
- Production-verified provider fallbacks:
  - Smartlead list-campaigns fallback when `limit` rejected.
  - HeyReach campaign/lead endpoint method/path fallbacks.
  - Graceful empty lead set when HeyReach lead APIs are not exposed for an account.

## Production Verification Snapshot

Recent commits deployed on `main`:
- `3a0e9e9` - HeyReach lead-list fallback variants
- `5aa9d16` - expanded HeyReach lead reconciliation fallback coverage
- `1d14c32` - graceful no-endpoint behavior for HeyReach lead APIs

Latest live verification result (scheduled reconciliation dry-run, HeyReach):
- HTTP 200
- provider errors: `[]`

Latest local verification pass:
- `pytest -q` => `48 passed`

Interpretation: HeyReach reconciliation is operationally stable for the currently connected tenant/API shape.

## What Remains (High Priority)

1. Authorization matrix expansion (phase increment completed)
- Webhook list/replay endpoints and LinkedIn role/company boundary tests are now covered.
- Non-LinkedIn campaign and internal provisioning role-boundary tests are now covered.
- Analytics and scheduler misuse coverage are now present in:
  - `tests/test_analytics_authorization_matrix.py`
  - `tests/test_internal_reconciliation_authorization_matrix.py`
  - `tests/test_webhooks_authorization_matrix.py`
  - `tests/test_internal_provisioning_authorization_matrix.py`
- Remaining work: incremental depth for edge-case permutations, not baseline access-control coverage.

2. Operator runbook (phase increment completed)
- `docs/WEBHOOK_INCIDENT_RUNBOOK.md` added with step-by-step incident recovery.
- Drill playbook added: `docs/WEBHOOK_RUNBOOK_DRILLS.md` (roles, cadence, scenarios, pass/fail, run template).
- Remaining work: execute drills and formalize ownership/on-call rotation conventions.

3. HeyReach message-history strategy (phase increment completed)
- Implemented explicit mode switch (`HEYREACH_MESSAGE_SYNC_MODE`) with safe default.
- Remaining work: provider/account-level validation to decide whether `pull_best_effort` should be enabled by default in production.

4. Metrics export strategy (phase increment completed)
- Durable snapshot sink added via `observability_metric_snapshots` with migration + super-admin flush/list endpoints.
- Reconciliation completion and webhook replay bulk/query now persist snapshots automatically.
- External sink forwarding now supported via env-configured export webhook (`OBSERVABILITY_EXPORT_URL` + optional bearer token/timeout), with best-effort failure handling.
- Remaining work: wire this export endpoint into your final APM/Prometheus/log pipeline destination and add destination-specific alerting/validation.

5. Retry policy classification refinement (phase increment completed)
- Provider error taxonomy now exposes transient/terminal categories in Smartlead/HeyReach exception surfaces.
- Router responses now map transient provider failures to `503` and terminal failures to `502` for clearer operator semantics.
- Remaining work: add taxonomy-aware alert routing thresholds.

## Recommended Next Execution Sequence

1. Execute runbook drills with operational owners and record outcomes.
2. Validate if/where `pull_best_effort` should be promoted from opt-in to default for HeyReach.
3. Add taxonomy-aware alert routing thresholds (transient burst vs terminal misconfig).
4. Extend authorization matrices for additional edge-case permutations (baseline analytics/internal scheduler misuse coverage is complete).
5. Integrate external sink destination ownership checks (payload contract validation, SLOs, and sink health monitors).

## Practical Readiness Assessment

- Architecture readiness for additional providers: **Yes**.
- Current platform reliability for Smartlead + HeyReach: **Good baseline, improving**.
- Main blocker before calling this fully operationally mature: **durable operational telemetry + operator process rigor**.

