1) Files changed
.env.example
src/config.py
src/routers/webhooks.py
src/routers/analytics.py
migrations/018_lob_reliability_indexes.sql
tests/test_webhooks_endpoint.py
tests/test_analytics_endpoint.py
docs/LOB_CANONICAL_HANDOFF.md
docs/LOB_IMPLEMENTED_ENDPOINT_REGISTRY.md
docs/LOB_OPERATOR_RUNBOOK.md
2) Endpoints/methods adjusted
Adjusted POST /api/webhooks/lob
Added strict schema validation before projection:
required identity (id/event_id)
required type (type/event_type/event)
required timestamp (date_created/created_at/time)
required resource reference (body.resource.id or fallback ids)
Added payload version guard:
accepted versions via LOB_WEBHOOK_SCHEMA_VERSIONS
unknown version -> dead-letter with version_unsupported
Validation failures now dead-letter deterministically with:
schema_invalid or version_unsupported
_schema_validation details persisted in payload envelope
No crash path; envelope remains replayable.
Adjusted replay control-plane endpoints (no new product surface):
POST /api/webhooks/replay-bulk
POST /api/webhooks/replay-query
POST /api/webhooks/dead-letters/replay
Added configurable replay concurrency + bounded queue:
LOB_WEBHOOK_REPLAY_MAX_CONCURRENT_WORKERS
LOB_WEBHOOK_REPLAY_QUEUE_SIZE
Preserved per-run caps and adaptive backpressure, with stronger transient-failure-driven delay scaling.
Added duplicate request-key suppression in replay bulk/dead-letter replay to preserve idempotent terminal effects.
Kept deterministic per-event result reporting.
Adjusted GET /api/analytics/direct-mail
Tightened max-row and range guards for performance/safety validation paths.
Kept auth boundary semantics unchanged.
Adjusted observability durability + SLO hooks
Added SLO threshold config hooks and metric-threshold events for:
signature reject rate
dead-letter creation rate
replay failure rate
projection failure rate
duplicate-ignore anomaly rate
Wired threshold checks into Lob webhook/replay metric snapshot flow.
Added/used metrics:
webhook.dead_letter.created
webhook.dead_letter.replayed
webhook.slo.threshold_exceeded
DB/index hardening
Added migrations/018_lob_reliability_indexes.sql for:
Lob dead-letter filtering (status/org/time + dead-letter reason expression index)
direct-mail analytics range scans on company_direct_mail_pieces (tenant-scoped created/updated and type/status paths)
3) Tests run + exact commands + totals
Command:
source .venv/bin/activate && PYTHONPATH=. pytest tests/test_webhooks_endpoint.py tests/test_webhooks_authorization_matrix.py tests/test_analytics_endpoint.py tests/test_analytics_authorization_matrix.py tests/test_direct_mail_endpoint.py tests/test_lob_client.py -q
Result:
63 passed, 8 warnings in 1.34s
Added/extended coverage includes:
strict schema validation accept/reject paths
unknown payload version handling
dead-letter reason correctness (schema_invalid, version_unsupported)
replay duplicate-key idempotency under concurrency controls
adaptive backpressure behavior under transient replay failures
dead-letter list pagination/filter logic
analytics max-rows/pagination logic
auth boundary checks remained in place
4) Remaining blockers/gaps
No blocker preventing Stage 5 rollout.
One practical gap remains intentionally configurable: unversioned Lob payloads are normalized to baseline v1 unless sender provides explicit version; strict rejection still applies for explicit unknown versions.
Existing non-blocking httpx deprecation warnings remain in webhook tests (data= raw upload path).
5) Readiness verdict for V2 Stage 5 only
ready for V2 Stage 5.
Reliability tightening goals are implemented: strict webhook validation/version guard, replay concurrency/backpressure controls, query/index hardening migration, SLO threshold hooks, runbook drill playbooks + decision tree, and passing targeted test coverage.