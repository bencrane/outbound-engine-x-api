# Webhook Incident Recovery Runbook

## Purpose

Recover webhook-driven state when provider events were missed, delayed, or partially applied.

This runbook covers:
- event discovery
- event inspection
- replay (single, bulk, query)
- verification

Applies to providers: `smartlead`, `heyreach`.

Drill companion: `docs/WEBHOOK_RUNBOOK_DRILLS.md`

## Required Access

- Super-admin JWT bearer token
- API base URL (prod or local)

Example environment:

```bash
export BASE_URL="https://api.outboundengine.dev"
export SA_TOKEN="<super_admin_jwt>"
export REQ_ID="incident-$(date +%s)"
```

## Endpoints Used

- `GET /api/webhooks/events`
- `POST /api/webhooks/replay/{provider_slug}/{event_key}`
- `POST /api/webhooks/replay-bulk`
- `POST /api/webhooks/replay-query`
- `POST /api/internal/reconciliation/campaigns-leads`

## 1) Detect + Scope

Identify provider, org/company scope, and incident time window.

Typical indicators:
- lead/campaign state in local DB does not match provider UI
- messages/replies missing from timeline
- elevated webhook failures in logs

## 2) List Candidate Events

List latest events for one provider:

```bash
curl -sS "$BASE_URL/api/webhooks/events?provider_slug=heyreach&limit=100" \
  -H "Authorization: Bearer $SA_TOKEN" \
  -H "X-Request-ID: $REQ_ID" | jq
```

Filter by org/company and event type:

```bash
curl -sS "$BASE_URL/api/webhooks/events?provider_slug=smartlead&org_id=<org_id>&company_id=<company_id>&event_type=reply&limit=200" \
  -H "Authorization: Bearer $SA_TOKEN" \
  -H "X-Request-ID: $REQ_ID" | jq
```

What to inspect per event:
- `event_key`
- `event_type`
- `status`
- `replay_count`
- `last_error`
- `created_at`

## 3) Replay Strategy

Choose smallest safe replay scope first.

### A. Replay Single Event (preferred first)

```bash
curl -sS -X POST "$BASE_URL/api/webhooks/replay/smartlead/<event_key>" \
  -H "Authorization: Bearer $SA_TOKEN" \
  -H "X-Request-ID: $REQ_ID" | jq
```

Expected:
- response `status: replayed`
- event `replay_count` increments
- event `status` becomes `replayed`

### B. Replay Bulk Explicit Keys

```bash
curl -sS -X POST "$BASE_URL/api/webhooks/replay-bulk" \
  -H "Authorization: Bearer $SA_TOKEN" \
  -H "Content-Type: application/json" \
  -H "X-Request-ID: $REQ_ID" \
  -d '{
    "provider_slug": "heyreach",
    "event_keys": ["evt-1","evt-2","evt-3"]
  }' | jq
```

Use when you already know exact failing keys.

### C. Replay by Query Window

```bash
curl -sS -X POST "$BASE_URL/api/webhooks/replay-query" \
  -H "Authorization: Bearer $SA_TOKEN" \
  -H "Content-Type: application/json" \
  -H "X-Request-ID: $REQ_ID" \
  -d '{
    "provider_slug": "smartlead",
    "org_id": "<org_id>",
    "company_id": "<company_id>",
    "from_ts": "2026-02-16T00:00:00Z",
    "to_ts": "2026-02-16T01:00:00Z",
    "limit": 200
  }' | jq
```

Use when incident is time-window based.

## 4) Verify Recovery

Run all checks:

1. Re-list events and confirm replay metadata updated.
2. Validate campaign/lead/message records in local DB/API now match expected provider state.
3. For broader drift, run reconciliation:

```bash
curl -sS -X POST "$BASE_URL/api/internal/reconciliation/campaigns-leads" \
  -H "Authorization: Bearer $SA_TOKEN" \
  -H "Content-Type: application/json" \
  -H "X-Request-ID: $REQ_ID" \
  -d '{
    "provider_slug": "smartlead",
    "org_id": "<org_id>",
    "company_id": "<company_id>",
    "dry_run": false
  }' | jq
```

4. Confirm no residual errors for affected provider window.

## 5) Escalation Conditions

Escalate if any is true:
- replay returns repeated provider 4xx/5xx failures
- event rows replay but target state remains unchanged
- reconciliation produces sustained provider fetch errors
- mismatch persists after replay + reconciliation

Capture for escalation:
- `X-Request-ID` used
- event keys replayed
- endpoint responses
- affected org/company/campaign IDs
- relevant log snippets

## Safety Rules

- Prefer single-event replay before bulk/query replay.
- Scope by provider + org/company whenever possible.
- Keep query replay `limit` conservative, iterate in batches.
- Always verify after replay before widening scope.
