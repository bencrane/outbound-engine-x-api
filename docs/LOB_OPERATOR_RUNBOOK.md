# Lob Operator Runbook (v1)

## Purpose

Operator-facing runbook for `direct_mail` on Lob covering incident triage, webhook diagnostics, replay workflows, and expected failure modes.

## Scope

In-scope Lob v1 workflows:

- Address verification (`/api/direct-mail/verify-address/us`, `/api/direct-mail/verify-address/us/bulk`)
- Postcards create/list/get/cancel
- Letters create/list/get/cancel
- Webhook ingest (`POST /api/webhooks/lob`) with idempotent projection into `company_direct_mail_pieces`
- Super-admin replay (`replay`, `replay-bulk`, `replay-query`)

Out of scope for this runbook:

- Cryptographic webhook signature validation implementation (pending provider contract)
- Deferred resources (self-mailers, checks)

## Incident Triage

When direct-mail behavior is degraded, triage in this order:

1. **Scope and tenancy validation**
   - Confirm request is operating under the expected `AuthContext.org_id`.
   - Confirm the company has `direct_mail` entitlement and `provider_slug=lob`.
   - Confirm org-level provider key exists (`organizations.provider_configs.lob.api_key`), or controlled fallback is configured.

2. **Route-level behavior**
   - Verify whether failure is in create/list/get/cancel path or webhook path.
   - Confirm route returns normalized provider error shape (`transient` maps to 503, terminal/provider contract errors map to 502 family as configured).

3. **Provider/backpressure symptoms**
   - Check for provider-side transient failures (429/5xx/timeout categories).
   - Confirm idempotency usage on write routes (`Idempotency-Key` header or `idempotency_key` query param, never both).

4. **Projection/state consistency**
   - Verify `company_direct_mail_pieces` row exists for piece and status is updated after write/get/list and webhook projection.
   - Compare provider piece status vs normalized internal status mapping.

## Webhook Backlog + Duplicate Diagnostics

Primary signals:

- `webhook.events.received` vs `webhook.events.processed`
- `webhook.events.duplicate`
- `webhook.events.failed`
- `webhook.replays.processed`, `webhook.replays.bulk`, `webhook.replays.query`

Diagnostic steps:

1. Query `webhook_events` for `provider_slug='lob'` by status, `created_at`, and `event_type`.
2. For duplicate spikes, inspect `event_key` reuse patterns and verify expected idempotent behavior (`duplicate_ignored`).
3. For failures, inspect `last_error` and the stored payload envelope to identify parsing/mapping gaps.
4. Confirm piece projection target exists (`company_direct_mail_pieces.external_piece_id`) for relevant events.

## Replay Workflow (Single -> Bulk -> Query)

Run replay in escalating order:

1. **Single replay**
   - Endpoint: `POST /api/webhooks/replay/{provider_slug}/{event_key}`
   - Use first for deterministic verification of one event path.

2. **Bulk replay**
   - Endpoint: `POST /api/webhooks/replay-bulk`
   - Use for bounded explicit event key sets after validating single replay behavior.

3. **Query replay**
   - Endpoint: `POST /api/webhooks/replay-query`
   - Use for time-window or status-based recovery when backlog is larger.

Operational guidance:

- Prefer smallest blast radius first.
- Validate normalized piece status updates before scaling replay batch size.
- Track replay metrics and post-replay failure residuals.

## Expected States and Failure Modes

Direct mail piece status normalization:

- `queued`, `processing`, `ready_for_mail`, `in_transit`, `delivered`, `returned`, `canceled`, `failed`, `unknown`

Common failure modes:

- Missing/invalid Lob API key configuration
- Entitlement/provider mismatch (`direct_mail` not mapped to Lob)
- Provider transient faults (429/5xx/timeouts)
- Provider terminal faults (validation or contract errors)
- Malformed webhook payloads (captured, non-crashing path)
- Missing local piece mapping during projection (event retained for audit/replay)

## Signature Verification Contract Status

`lob.webhooks.signature_contract` is still `blocked_contract_missing`.

Current runtime behavior for Lob webhook ingest is explicitly:

- verification mode: `disabled_pending_contract`
- no cryptographic signature validation is performed yet

Do not implement signature crypto until canonical provider contract is confirmed.
