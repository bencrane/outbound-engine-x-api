# Lob Operator Runbook (v1)

## Purpose

Operator-facing runbook for `direct_mail` on Lob covering incident triage, webhook diagnostics, replay workflows, and expected failure modes.

## Scope

In-scope Lob v1 workflows:

- Address verification (`/api/direct-mail/verify-address/us`, `/api/direct-mail/verify-address/us/bulk`)
- Postcards create/list/get/cancel
- Letters create/list/get/cancel
- Self-mailers create/list/get/cancel
- Checks create/list/get/cancel
- Webhook ingest (`POST /api/webhooks/lob`) with idempotent projection into `company_direct_mail_pieces`
- Super-admin replay (`replay`, `replay-bulk`, `replay-query`)

Out of scope for this runbook:

- Signature/compliance controls beyond current enforced contract (future schema-version strictness / DLQ policies).

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

### Replay throttling and guardrails (Lob)

Lob replay paths enforce operator safety controls:

- `LOB_WEBHOOK_REPLAY_MAX_EVENTS_PER_RUN` (hard cap per replay request)
- `LOB_WEBHOOK_REPLAY_BATCH_SIZE` (events per batch)
- `LOB_WEBHOOK_REPLAY_SLEEP_MS` (base inter-batch sleep)
- `LOB_WEBHOOK_REPLAY_BACKOFF_MULTIPLIER` and `LOB_WEBHOOK_REPLAY_MAX_SLEEP_MS` (adaptive slowdown when failures occur)

Operator guidance:

- Keep max-events low during incident response to reduce blast radius.
- Increase sleep and reduce batch size if `replay_failed` rises.
- Prefer query replay with narrow filters (provider + org + event type + time window).

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

## Dead-letter Triage and Recovery

Dead-letter events are stored in `webhook_events` with `status=dead_letter`, preserved payload, failure reason, and retryability metadata.

Common dead-letter reasons:

- `malformed_payload`
- `projection_unresolved`
- `projection_failure`

Recovery flow:

1. Query dead-letter rows scoped by provider/org/company and newest first.
2. Inspect payload + `_dead_letter.reason` + `last_error`.
3. Fix root cause (mapping/config/code).
4. Reprocess using existing replay endpoint(s) with bounded batches.
5. Confirm status transitions to `replayed` and piece state is updated.

If replay still fails, keep the event in dead-letter and escalate with logs/metrics attached.

## Signature Verification Operations

Lob webhook signature verification is implemented using:

- `Lob-Signature`
- `Lob-Signature-Timestamp`
- HMAC-SHA256 over `<timestamp>.<raw_request_body>`

Runtime modes:

- `permissive_audit`: verify and annotate/log result, do not reject request for signature failures
- `enforce`: reject invalid/missing/stale signatures with deterministic auth error shape

Timestamp/replay window:

- Enforced against `LOB_WEBHOOK_SIGNATURE_TOLERANCE_SECONDS` (default 300s)

Incident handling:

- If signature failures spike in `permissive_audit`, investigate before promoting to `enforce`.
- If `enforce` is enabled without `LOB_WEBHOOK_SECRET`, service returns configuration error and must be remediated immediately.

### Signature rollout playbook (`permissive_audit` -> `enforce`)

1. Start in `permissive_audit`.
2. Monitor signature failure reasons (`missing_signature`, `missing_timestamp`, `invalid_timestamp`, `stale_timestamp`, `invalid_signature`) until stable/near-zero.
3. Fix upstream sender/header issues.
4. Enable `enforce` in controlled environment first.
5. Promote to production `enforce` only after sustained clean window.

Rollback: switch mode back to `permissive_audit` if rejection spikes threaten delivery.

## Recommended Alert Thresholds (starting points)

- **webhook rejected rate**: `webhook.events.rejected / webhook.events.received > 1%` for 5m
- **signature failure spike**: any single signature-failure reason > 20 events/5m
- **duplicate spike**: `webhook.duplicate_ignored / webhook.events.received > 10%` for 15m
- **projection failure**: `webhook.projection.failure > 0` sustained for 5m
- **replay health**: `webhook.replay_failed > 0` or replay backlog increasing for 15m
