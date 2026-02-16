# Lob Implemented Endpoint Registry

Generated: 2026-02-16

Canonical source: `https://docs.lob.com`

Purpose: strict proof of what Lob endpoints are implemented in this repo for `direct_mail`, with explicit status:

- `implemented`
- `deferred`
- `blocked_contract_missing`

## Source Of Truth In Code

- Provider client registry constant: `src/providers/lob/client.py` -> `LOB_IMPLEMENTED_ENDPOINT_REGISTRY`
- Contract status registry constant: `src/providers/lob/client.py` -> `LOB_CONTRACT_STATUS_REGISTRY`
- Guard test: `tests/test_lob_client.py::test_registry_covers_all_public_client_methods`

Stage 5/v2-5 note: Lob provider client foundation, direct-mail capability workflows (postcards/letters/self-mailers/checks), webhook ingestion/projection/replay, operator hardening, signature verification, dead-letter control plane APIs, direct-mail analytics, and production reliability tightening controls are implemented.

## Registry Rows (Stage 0 Baseline)

| Domain | Method | Path | Internal operation (planned) | Status | Notes |
|---|---|---|---|---|---|
| Address verification | POST | `/v1/us_verifications` | `verify_address_us_single()` | implemented | Stage 2 routed via `/api/direct-mail/verify-address/us` |
| Address verification | POST | `/v1/bulk/us_verifications` | `verify_address_us_bulk()` | implemented | Stage 2 routed via `/api/direct-mail/verify-address/us/bulk` |
| Addresses | POST | `/v1/addresses` | `create_address()` | deferred | optional support for reusable address objects |
| Addresses | GET | `/v1/addresses` | `list_addresses()` | deferred | optional support |
| Addresses | GET | `/v1/addresses/{adr_id}` | `get_address()` | deferred | optional support |
| Addresses | DELETE | `/v1/addresses/{adr_id}` | `delete_address()` | deferred | optional support |
| Postcards | POST | `/v1/postcards` | `create_postcard()` | implemented | Stage 2 routed via `/api/direct-mail/postcards` |
| Postcards | GET | `/v1/postcards` | `list_postcards()` | implemented | Stage 2 routed via `/api/direct-mail/postcards` |
| Postcards | GET | `/v1/postcards/{psc_id}` | `get_postcard()` | implemented | Stage 2 routed via `/api/direct-mail/postcards/{piece_id}` |
| Postcards | DELETE | `/v1/postcards/{psc_id}` | `cancel_postcard()` | implemented | Stage 2 routed via `/api/direct-mail/postcards/{piece_id}/cancel` |
| Letters | POST | `/v1/letters` | `create_letter()` | implemented | Stage 2 routed via `/api/direct-mail/letters` |
| Letters | GET | `/v1/letters` | `list_letters()` | implemented | Stage 2 routed via `/api/direct-mail/letters` |
| Letters | GET | `/v1/letters/{ltr_id}` | `get_letter()` | implemented | Stage 2 routed via `/api/direct-mail/letters/{piece_id}` |
| Letters | DELETE | `/v1/letters/{ltr_id}` | `cancel_letter()` | implemented | Stage 2 routed via `/api/direct-mail/letters/{piece_id}/cancel` |
| Self-mailers | POST | `/v1/self_mailers` | `create_self_mailer()` | implemented | V2 Stage 2 routed via `/api/direct-mail/self-mailers` |
| Self-mailers | GET | `/v1/self_mailers` | `list_self_mailers()` | implemented | V2 Stage 2 routed via `/api/direct-mail/self-mailers` |
| Self-mailers | GET | `/v1/self_mailers/{sfm_id}` | `get_self_mailer()` | implemented | V2 Stage 2 routed via `/api/direct-mail/self-mailers/{piece_id}` |
| Self-mailers | DELETE | `/v1/self_mailers/{sfm_id}` | `cancel_self_mailer()` | implemented | V2 Stage 2 routed via `/api/direct-mail/self-mailers/{piece_id}/cancel` |
| Checks | POST | `/v1/checks` | `create_check()` | implemented | V2 Stage 2 routed via `/api/direct-mail/checks` |
| Checks | GET | `/v1/checks` | `list_checks()` | implemented | V2 Stage 2 routed via `/api/direct-mail/checks` |
| Checks | GET | `/v1/checks/{chk_id}` | `get_check()` | implemented | V2 Stage 2 routed via `/api/direct-mail/checks/{piece_id}` |
| Checks | DELETE | `/v1/checks/{chk_id}` | `cancel_check()` | implemented | V2 Stage 2 routed via `/api/direct-mail/checks/{piece_id}/cancel` |
| Webhooks/events | POST | `/api/webhooks/lob` (inbound) | `ingest_lob_webhook()` | implemented | Stage 3 ingest + dedupe + normalized projection + replay support |
| Webhooks/events | N/A | signature verification contract | `verify_webhook_signature()` | implemented | `Lob-Signature` + `Lob-Signature-Timestamp`, HMAC-SHA256 over `<timestamp>.<raw_body>`, timestamp tolerance enforcement |
| Idempotency | N/A | write-request idempotency contract | `build_idempotency_headers()` | deferred | documented: `Idempotency-Key` header or `idempotency_key` query param, 24h retention, never send both at once |

## Status Summary

- `implemented`: 20
- `deferred`: 5
- `blocked_contract_missing`: 0

## Blocked Contract Items

- None currently.

## Deferred Contract Items

- `lob.idempotency.write_contract` -> deferred
  - Canonical contract for implementation: `Idempotency-Key` header is supported, `idempotency_key` query param is supported, key retention is 24 hours, and clients must not send both forms simultaneously.

## Dispatch Wiring (Stage 1)

- `direct_mail -> lob` capability/provider provisioning path is implemented in `src/routers/internal_provisioning.py`:
  - `POST /api/internal/provisioning/direct-mail/{company_id}`
  - `GET /api/internal/provisioning/direct-mail/{company_id}/status`
- Entitlement/provider resolution remains org-scoped and uses existing company entitlement flow.

## Capability-Facing API (Stage 2)

- `POST /api/direct-mail/verify-address/us`
- `POST /api/direct-mail/verify-address/us/bulk`
- `POST /api/direct-mail/postcards`
- `GET /api/direct-mail/postcards`
- `GET /api/direct-mail/postcards/{piece_id}`
- `POST /api/direct-mail/postcards/{piece_id}/cancel`
- `POST /api/direct-mail/letters`
- `GET /api/direct-mail/letters`
- `GET /api/direct-mail/letters/{piece_id}`
- `POST /api/direct-mail/letters/{piece_id}/cancel`

## Capability-Facing API (V2 Stage 2)

- `POST /api/direct-mail/self-mailers`
- `GET /api/direct-mail/self-mailers`
- `GET /api/direct-mail/self-mailers/{piece_id}`
- `POST /api/direct-mail/self-mailers/{piece_id}/cancel`
- `POST /api/direct-mail/checks`
- `GET /api/direct-mail/checks`
- `GET /api/direct-mail/checks/{piece_id}`
- `POST /api/direct-mail/checks/{piece_id}/cancel`

## Capability-Facing API (V2 Stage 4)

- `GET /api/analytics/direct-mail`
  - normalized direct-mail analytics rollup
  - supports `company_id` and org-admin `all_companies=true`
  - includes piece volume by type/status, delivery funnel, failure/rejection reasons, and daily trends

## Super-Admin Control Plane API (V2 Stage 4)

- `GET /api/webhooks/dead-letters`
- `GET /api/webhooks/dead-letters/{event_key}`
- `POST /api/webhooks/dead-letters/replay`

Notes:
- Dead-letter APIs are Lob-scoped and super-admin protected.
- Existing replay endpoints remain compatible (`replay`, `replay-bulk`, `replay-query`).

## Reliability Controls (V2 Stage 5)

- Webhook strict schema validation + version guard on `POST /api/webhooks/lob`
  - required identity/type/timestamp/resource checks
  - unknown schema version deterministic dead-letter route (`version_unsupported`)
  - schema validation failures deterministic dead-letter route (`schema_invalid`)
- Replay worker controls on Lob replay paths:
  - `LOB_WEBHOOK_REPLAY_MAX_CONCURRENT_WORKERS`
  - `LOB_WEBHOOK_REPLAY_QUEUE_SIZE`
  - bounded queue + adaptive backpressure under transient replay failures
- SLO calibration hooks wired to metric pipeline:
  - signature reject rate
  - dead-letter creation rate
  - replay failure rate
  - projection failure rate
  - duplicate ignore anomaly rate
- Index hardening migration:
  - `migrations/018_lob_reliability_indexes.sql`

## Webhook + Replay (Stage 3)

- Inbound endpoint implemented:
  - `POST /api/webhooks/lob`
- Ingest behavior implemented:
  - provider event dedupe key generation + idempotent persistence in `webhook_events`
  - normalized Lob event projection to direct-mail piece statuses
  - signature verification with mode switch:
    - `permissive_audit` (audit-only)
    - `enforce` (reject invalid/missing/stale signatures)
- Super-admin replay surfaces now include `lob`:
  - `POST /api/webhooks/replay/{provider_slug}/{event_key}`
  - `POST /api/webhooks/replay-bulk`
  - `POST /api/webhooks/replay-query`

## Operator Hardening (Stage 4)

- Direct-mail route observability is implemented for:
  - create/list/get/cancel flows across postcards and letters
  - provider error taxonomy surfacing with structured failure logs
- Correlated request-id logging is wired where request context is available.
- Operator runbook published:
  - `docs/LOB_OPERATOR_RUNBOOK.md`
- Durable observability snapshots now include Lob webhook ingress/rejection/replay/dead-letter flows and direct-mail analytics source snapshots.

## Stage Alignment

- Stage 0: docs only (completed).
- Stage 1: provider client skeleton + capability wiring (`direct_mail`) (completed).
- Stage 2: postcard/letter/address-verification workflows + normalized contracts + dispatch tests (completed).
- Stage 3: webhook ingestion + idempotent projection + replay support (completed).
- Stage 4: operator hardening + broader regression + release closure docs (completed).
- Lob v2 Stage 1: webhook signature verification closure + replay-window enforcement (completed).
- Lob v2 Stage 2: self-mailers + checks capability rollout with tenant-safe dispatch (completed).

## Guardrail

Do not mark any Lob row as `implemented` until both are true:

- method/path is wired in `src/providers/lob/client.py` and dispatched through capability abstraction, and
- targeted tests cover success + auth boundary + normalization/error path behavior.
