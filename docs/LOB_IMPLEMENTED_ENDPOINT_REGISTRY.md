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

Stage 2 note: Lob provider client foundation and direct-mail capability-facing workflows are implemented for address verification, postcards, and letters.

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
| Self-mailers | POST | `/v1/self_mailers` | `create_self_mailer()` | deferred | out of v1 scope |
| Self-mailers | GET | `/v1/self_mailers` | `list_self_mailers()` | deferred | out of v1 scope |
| Self-mailers | GET | `/v1/self_mailers/{sfm_id}` | `get_self_mailer()` | deferred | out of v1 scope |
| Self-mailers | DELETE | `/v1/self_mailers/{sfm_id}` | `delete_self_mailer()` | deferred | out of v1 scope |
| Checks | POST | `/v1/checks` | `create_check()` | deferred | out of v1 scope |
| Checks | GET | `/v1/checks` | `list_checks()` | deferred | out of v1 scope |
| Checks | GET | `/v1/checks/{chk_id}` | `get_check()` | deferred | out of v1 scope |
| Checks | DELETE | `/v1/checks/{chk_id}` | `cancel_check()` | deferred | out of v1 scope |
| Webhooks/events | N/A | inbound webhook receiver in this API | `ingest_tracking_event()` | deferred | endpoint path to be added in Stage 3 |
| Webhooks/events | N/A | signature verification contract | `verify_webhook_signature()` | blocked_contract_missing | exact signing contract not locked |
| Idempotency | N/A | write-request idempotency contract | `build_idempotency_headers()` | deferred | documented: `Idempotency-Key` header or `idempotency_key` query param, 24h retention, never send both at once |

## Status Summary

- `implemented`: 10
- `deferred`: 14
- `blocked_contract_missing`: 1

## Blocked Contract Items

- `lob.webhooks.signature_contract` -> `blocked_contract_missing`
  - Missing exact signature header/algorithm/canonicalization/replay requirements in currently extracted canonical docs.

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

## Stage Alignment

- Stage 0: docs only (completed).
- Stage 1: provider client skeleton + capability wiring (`direct_mail`) (completed).
- Stage 2: postcard/letter/address-verification workflows + normalized contracts + dispatch tests (completed).
- Stage 3: webhook ingestion + signature verification after contract unblock.

## Guardrail

Do not mark any Lob row as `implemented` until both are true:

- method/path is wired in `src/providers/lob/client.py` and dispatched through capability abstraction, and
- targeted tests cover success + auth boundary + normalization/error path behavior.
