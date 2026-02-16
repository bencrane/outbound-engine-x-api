# Lob Canonical Handoff

Generated: `2026-02-16T03:33:25Z` (UTC)

## Canonical Source

- Canonical API source: `https://docs.lob.com` (OpenAPI/Redoc docs).
- Supporting operational guidance: Lob Help Center pages linked from the docs.
- This document is the canonical planning source for `direct_mail` capability integration in this repo.

## Current Scope Snapshot

- Stage 0 (canonical discovery + planning) is complete.
- Stage 1 (provider foundation + capability wiring) is implemented.
- Stage 2 (direct-mail workflow rollout for address verification + postcards + letters) is implemented.
- Stage 3 (Lob webhook ingestion + idempotent projection + replay glue) is implemented with signature verification intentionally gated.
- Stage 4 (operator hardening + regression sweep + release closure) is implemented.

## 1) Lob Surface Mapped To Internal Capability Model

Client-facing capability remains `direct_mail` (provider-agnostic).  
Provider internals (Lob endpoint names/IDs) stay inside provider adapter + normalization layer.

### Capability domains for v1 planning

- `direct_mail.address_verification`
  - Lob: US Verifications (`single`, `bulk`), optional Address object create/retrieve/list for storage workflows.
- `direct_mail.postcards`
  - Lob: create/list/retrieve/cancel postcard.
- `direct_mail.letters`
  - Lob: create/list/retrieve/cancel letter.
- `direct_mail.webhook_events`
  - Lob: event subscriptions + tracking event payload ingestion (inbound webhook receiver in this repo).

### Deferred domains (not in v1 operator-grade MVP)

- `direct_mail.self_mailers` -> deferred
- `direct_mail.checks` -> deferred

### Surfaces explicitly avoided in v1

- Campaigns API (marked `BETA` in Lob docs) -> avoid for v1.
- Informed Delivery Campaign API -> avoid for v1.
- Any unstable/beta surfaces beyond core postcard/letter/address verification/eventing.

## 2) Canonical Lob Endpoint Families (Docs-grounded)

From `https://docs.lob.com`:

- Auth: HTTP Basic auth (`API key as username`, blank password).
- Addresses: create/retrieve/list/delete.
- US Verifications: single verify, bulk verify (+ test env behavior docs).
- Postcards: create/retrieve/list/cancel.
- Letters: create/retrieve/list/cancel.
- Self Mailers: create/retrieve/list/delete (deferred).
- Checks: create/retrieve/list/cancel (deferred).
- Webhooks/Events/Tracking Events: webhook-driven tracking/event delivery model.
- Appendix includes idempotent requests and request/response conventions.

## 3) Auth Model Differences (Explicit)

### Outbound Engine X auth

- Incoming caller auth is API token or JWT -> yields `AuthContext` with `org_id`.
- `org_id` is never accepted from payload.

### Lob provider auth

- Outbound provider call auth is HTTP Basic with Lob API key.
- For this integration, only use env key `LOB_API_KEY_TEST` during implementation/testing.
- Provider credentials must remain server-side only.

### Implication for architecture

- `AuthContext.org_id` scopes all local data and entitlement resolution.
- Provider key resolution must happen after tenant checks, never from request payload.
- Client contracts expose only `direct_mail` semantics, never Lob-specific auth details.

## 4) Idempotency + Retry + Rate Limits

### Idempotency

- Lob docs expose an "Idempotent Requests" appendix section.
- Canonical implementation details for Stage 1:
  - `Idempotency-Key` header is supported.
  - `idempotency_key` query parameter is supported.
  - Key retention/expiry window is 24 hours.
  - Do not send both header and query idempotency key on the same request.
- Stage status: documented and usable for implementation (deferred, not blocked).

### Rate limits

- Lob responses include rate-limit headers in endpoint docs/examples:
  - `ratelimit-limit`
  - `ratelimit-remaining`
  - `ratelimit-reset`
- Error guidance recommends backoff/retry behavior for 429/5xx/timeouts and use of idempotency keys for safe retries.

### Retry expectations for v1

- Retry on transient provider failures (5xx, network timeouts, 429) with bounded exponential backoff + jitter.
- Do not retry deterministic 4xx validation/auth failures.
- Keep retry semantics provider-internal; expose stable normalized API errors upstream.

## 5) Proposed Normalized Direct-Mail Taxonomy (Internal)

This is an internal normalization contract, not a client-facing provider leak.

### Piece status taxonomy (`direct_mail_piece.status`)

- `queued` (accepted by provider, not yet in production)
- `processing` (render/print prep in progress)
- `ready_for_mail` (production complete, pending handoff)
- `in_transit` (entered carrier stream)
- `delivered` (delivered/complete)
- `returned` (undeliverable/returned)
- `canceled` (canceled before mail handoff)
- `failed` (terminal production or validation failure)
- `unknown` (unmapped provider state)

### Event taxonomy (`direct_mail_event.type`)

- `piece.created`
- `piece.updated`
- `piece.processed`
- `piece.in_transit`
- `piece.delivered`
- `piece.returned`
- `piece.canceled`
- `piece.re-routed` (for address move/NCOA style outcomes where applicable)
- `piece.failed`
- `piece.unknown`

### Address verification taxonomy (`direct_mail_address_verification.status`)

- `deliverable`
- `undeliverable`
- `corrected`
- `partial`
- `unknown`

## 6) v1 Operator-Grade MVP (Definition)

### In scope (v1)

- Provider adapter scaffolding under `src/providers/lob/` with strict org-scoped dispatch from capability `direct_mail`.
- Address verification (US single + bulk where practical in existing router patterns).
- Postcards create/list/retrieve/cancel.
- Letters create/list/retrieve/cancel.
- Webhook ingestion path for Lob tracking events with:
  - signature verification once contract is confirmed,
  - idempotent event processing,
  - normalized event projection.
- Test coverage mirroring existing provider pattern:
  - provider client unit tests,
  - router dispatch/auth-boundary tests,
  - normalization tests,
  - webhook auth/idempotency tests.
- Docs updates (API + registry + handoff updates by slice).

### Out of scope (v1)

- Self-mailers.
- Checks.
- Lob Campaigns API (beta).
- Informed Delivery Campaign API.
- Non-essential Lob specialty resources (buckslips/cards/QR/url shortener/billing groups) unless explicitly requested in later stages.

## 7) Contract Gaps / Ambiguities (Stage 0)

Tracked as blockers where implementation requires exact contract details:

- `lob.webhooks.signature_contract` -> `blocked_contract_missing`
  - Missing precise canonical details in currently fetchable docs: signing header name(s), algorithm, payload canonicalization rules, replay/timestamp tolerance.

Non-blocking items:

- Core endpoint families and capability mapping are clear for staged implementation.
- Deferred status for self-mailers/checks is explicit and intentional.
- `lob.idempotency.write_contract` is deferred (not blocked): `Idempotency-Key` header or `idempotency_key` query parameter, 24-hour key retention, never both simultaneously.

## 8) Staged Implementation Plan (Repo-Aligned)

### Stage 1 - Provider foundation + capability wiring (implemented)

- Add `direct_mail` capability and Lob provider mapping in entitlement layer (DB + seed + docs/tests as needed).
- Create `src/providers/lob/client.py` with:
  - auth plumbing from env/config (`LOB_API_KEY_TEST` only for test env),
  - address verification + postcard + letter basic methods,
  - provider error normalization skeleton.
- Add provider dispatch entry points in direct-mail routers without leaking provider internals.
- Add registry constants and guard tests similar to existing provider patterns.

Stage 1 implementation status:

- Implemented migration to seed `direct_mail` capability and `lob` provider mapping.
- Implemented Lob provider client scaffold with:
  - retry/backoff skeleton and provider error normalization,
  - idempotency helper (`Idempotency-Key` header or `idempotency_key` query param, mutually exclusive),
  - address verification, postcards, and letters endpoint methods.
- Implemented internal provisioning/dispatch hooks for direct mail entitlement resolution:
  - `POST /api/internal/provisioning/direct-mail/{company_id}`
  - `GET /api/internal/provisioning/direct-mail/{company_id}/status`
- Added targeted tests for Lob client contracts, idempotency behavior, registry drift guard, and direct_mail->lob provisioning/dispatch resolution.

### Stage 2 - Route rollout + normalization (implemented)

- Implement postcard/letter create/list/retrieve/cancel paths behind capability abstraction.
- Implement address verification endpoints behind capability abstraction.
- Add normalization layer for piece statuses/events/address-verification outcomes.
- Add focused tests for tenant scoping, dispatch correctness, and normalized response contracts.

Stage 2 implementation status:

- Implemented capability-facing direct-mail routes:
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
- Implemented normalized response contracts for piece and address verification outputs.
- Implemented direct_mail entitlement/provider dispatch handling with explicit non-Lob provider `not implemented` behavior.
- Added `company_direct_mail_pieces` persistence mapping for tenant-safe piece retrieval/cancel/list behavior.
- Added targeted endpoint tests for happy paths, auth boundaries, provider dispatch, validation errors, normalized contracts, and provider error-shape behavior.

### Stage 3 - Webhooks + idempotency hardening (implemented, signature gated)

- Add Lob webhook endpoint in `src/routers/webhooks.py`.
- Implement signature verification once `lob.webhooks.signature_contract` is resolved.
- Implement idempotent event ingestion/dedupe and replay protection.
- Add webhook authorization + dedupe + normalization tests.

Stage 3 implementation status:

- Implemented Lob inbound webhook endpoint:
  - `POST /api/webhooks/lob`
- Implemented idempotent event ingestion:
  - stable dedupe key derivation with provider event identity fallback
  - event envelope persistence in `webhook_events`
  - deterministic duplicate handling (`duplicate_ignored`)
- Implemented normalized Lob event projection to direct-mail piece state:
  - `piece.created|updated|processed|in_transit|delivered|returned|canceled|re-routed|failed|unknown`
  - projection into `company_direct_mail_pieces.status` + update timestamps
- Integrated replay support for Lob into existing super-admin replay endpoints (single/bulk/query).
- Signature verification remains explicitly gated:
  - processing mode is `disabled_pending_contract` (no cryptographic verification rules implemented yet).

### Stage 4 - Operator hardening + deferred scope revisit

- Observability metrics and structured logs for direct-mail create/list/get/cancel and provider error paths.
- Correlation/request-id propagation for direct-mail route logs where request context is available.
- Operator runbook published: `docs/LOB_OPERATOR_RUNBOOK.md` (incident triage, webhook duplicate diagnostics, replay workflow, failure modes).
- Full regression sweep across direct-mail, webhooks, provisioning/auth boundary, and provider/core regression suites.
- Reassess deferred domains (self-mailers/checks) based on product need.

Stage 4 implementation status:

- Added direct-mail route instrumentation:
  - `direct_mail.requests.received`
  - `direct_mail.requests.processed`
  - `direct_mail.requests.failed` (including provider error category + retryability labels)
- Added structured event logging for direct-mail operation success/failure and provider-not-implemented paths.
- Confirmed webhook ingest + duplicate + replay observability remains active for `lob`.
- Added operator runbook and linked operational procedures for replay escalation and diagnostics.
- Completed broader regression sweep for Lob + existing provider/core suites.

## 11) Operator Runbook

- Primary runbook: `docs/LOB_OPERATOR_RUNBOOK.md`
- Covers:
  - direct-mail incident triage,
  - webhook backlog/duplicate diagnostics,
  - replay escalation flow (single -> bulk -> query),
  - expected status states and failure modes,
  - explicit signature-verification pending-contract note.

## 12) Multi-Tenant Safety Requirements (Implementation Guardrails)

- Every tenant data read/write must scope by `org_id` from `AuthContext`.
- Never accept `org_id` from request payloads.
- Entitlement/provider resolution must happen inside org boundary checks.
- Error responses must not leak cross-org existence.
- Provider IDs/object IDs must not be treated as globally trustworthy; always map and validate within tenant scope.

## 13) Current Readiness Verdict

`ready_with_blockers`

Rationale:

- Lob v1 direct-mail workflows (verification/postcards/letters), webhook ingest/projection/replay, and operator hardening are implemented.
- Full regression coverage for Lob paths and key provider/core suites has passed.
- Remaining blocker is isolated to `lob.webhooks.signature_contract` (`blocked_contract_missing`) without blocking non-dependent runtime operation.
