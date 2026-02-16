# EmailBison Canonical Handoff

Generated: `2026-02-16T02:17:02Z` (UTC)

## Canonical Source + Naming Caveat

- MCP server name is `user-emailbison` (not `emailbison`).
- Canonical source of truth is live MCP (`user-emailbison`) plus current API spec/tool output.
- `archive/emailbison/*` is deprecated historical artifact content and must not be used as canonical source.

## 1) Connectivity + Tooling Verification

### Smoke Test Matrix

| Check | Tool name (exact) | Input | Result |
|---|---|---|---|
| Reachability via MCP resource fetch | `FetchMcpResource` | `server=user-emailbison`, `uri=emailbison://resources/system-instructions` | **PASS** |
| Tool inventory discovery | `user-emailbison-discover_tools` | default | **PASS** (`total_tools=141`, `core_tools=23`) |
| API spec lookup - campaigns | `user-emailbison-search_api_spec` | `endpoint=/api/campaigns` | **PASS** |
| API spec lookup - leads | `user-emailbison-search_api_spec` | `endpoint=/api/leads` | **PASS** |
| API spec lookup - replies | `user-emailbison-search_api_spec` | `endpoint=/api/replies` | **PASS** |
| API spec lookup - webhooks | `user-emailbison-search_api_spec` | `search_term=webhooks` | **PASS** (resolved to `/api/webhook-url`) |

### Notes

- Earlier check against server name `emailbison` failed (`Server "emailbison" not found`), confirming the naming caveat is operationally important.
- API spec lookups returned valid endpoint definitions for required domains.
- MCP tool counts are version-dependent snapshots; count deltas alone should not be treated as regressions.

## 2) Canonical Capability Audit (Live MCP + API Spec)

Confidence rubric:
- **High**: endpoint/tool behavior is explicit and consistent in current outputs.
- **Medium**: available but with shape/path ambiguity or partial discoverability.
- **Low**: incomplete discoverability in current tool/spec responses.

### Campaigns

- **Endpoints**
  - `GET /api/campaigns`
  - `POST /api/campaigns`
  - `POST /api/campaigns/{campaign_id}/stats`
  - `PATCH /api/campaigns/{campaign_id}/pause` (status write)
  - `PATCH /api/campaigns/{campaign_id}/resume` (status write)
  - `PATCH /api/campaigns/{campaign_id}/archive` (status write)
- **Required params**
  - Create: `name` required, `type` optional (`outbound`/`reply_followup` in examples).
  - Stats summary: `start_date`, `end_date` required.
  - List: supports `search`, `status`, `tag_ids` (shown in request schema).
- **Key response fields**
  - `id`, `uuid`, `name`, `type`, `status`
  - `emails_sent`, `opened`, `unique_opens`, `replied`, `unique_replies`, `bounced`, `unsubscribed`, `interested`
  - `total_leads_contacted`, `total_leads`, `tags`, `created_at`, `updated_at`
- **Known caveats/inconsistencies**
  - List spec models filter fields in a request body shape even though endpoint method is `GET`.
  - Status examples use mixed casing (`Active`, `Launching`) and enum strings include values like `pending deletion`.
  - Live spec confirmation pass found action endpoints for status writes (`pause`/`resume`/`archive`) rather than a generic `PATCH /api/campaigns/{campaign_id}/status` contract.
- **Confidence**: **High**

### Leads

- **Endpoints**
  - `GET /api/leads`
  - `POST /api/leads`
  - `POST /api/leads/multiple`
  - `POST /api/leads/create-or-update/multiple`
- **Required params**
  - Create single: `first_name`, `last_name`, `email`.
  - Bulk create: `leads[]` with same required lead keys.
  - List filters use nested query keys like `filters.lead_campaign_status`, `filters.emails_sent.criteria`, `filters.verification_statuses`, date filters.
- **Key response fields**
  - `id`, `first_name`, `last_name`, `email`, `title`, `company`, `notes`, `status`
  - `custom_variables[]`, `lead_campaign_data`, `overall_stats` (`emails_sent`, `opens`, `replies`, etc.)
  - `created_at`, `updated_at`
- **Known caveats/inconsistencies**
  - Some schema examples include minor JSON defects in examples (formatting/comma issues), but top-level field model is usable.
  - Status vocabulary includes verification-state values that must be normalized for local model.
- **Confidence**: **High**

### Inbox / Replies

- **Endpoints**
  - `GET /api/replies`
  - `GET /api/replies/{id}`
  - `GET /api/replies/{reply_id}/conversation-thread`
- **Required params**
  - List filters: `search`, `status`, `folder`, `read`, `campaign_id`, `sender_email_id`, `lead_id`, `tag_ids` (all optional).
- **Key response fields**
  - `id`, `uuid`, `folder`, `subject`, `read`, `interested`, `automated_reply`
  - `html_body`, `text_body`, `date_received`
  - `campaign_id`, `lead_id`, `sender_email_id`, `from_email_address`, `to[]`, `attachments[]`
- **Known caveats/inconsistencies**
  - Core MCP tool `send_reply` exists, but corresponding canonical spec endpoint path was not directly surfaced by quick endpoint queries (requires stricter endpoint/path discovery in implementation phase).
  - Reply IDs appear as `{id}` in one spec result and `{reply_id}` in others.
- **Confidence**: **Medium**

### Sender Emails

- **Endpoints**
  - `GET /api/sender-emails`
  - `GET /api/sender-emails/{senderEmailId}`
  - `POST /api/sender-emails/imap-smtp`
  - `PATCH /api/sender-emails/{senderEmailId}`
  - `DELETE /api/sender-emails/{senderEmailId}`
- **Required params**
  - IMAP/SMTP create requires: `name`, `email`, `password`, `imap_server`, `imap_port`, `smtp_server`, `smtp_port`.
  - Update accepts optional settings like `daily_limit`, `name`, `email_signature`.
- **Key response fields**
  - `id`, `name`, `email`, `status`, `type`
  - `daily_limit`, IMAP/SMTP metadata
  - aggregate counters: `emails_sent_count`, `total_replied_count`, `total_opened_count`, `bounced_count`, `interested_leads_count`, etc.
- **Known caveats/inconsistencies**
  - Both flat filter params (`tag_ids`, `without_tags`) and nested filter forms (`filters.without_tags`) appear.
- **Confidence**: **High**

### Webhooks

- **Canonical endpoint path (locked from live API spec)**
  - `/api/webhook-url` (collection)
  - `/api/webhook-url/{id}` (single resource read/update)
  - `/api/webhook-url/{webhook_url_id}` (single resource delete)
- **Aliases / deprecated / non-canonical notes**
  - `/api/webhooks` is **not** present in live API spec output.
  - `{id}` and `{webhook_url_id}` appear as path parameter variants for single-resource operations; treat `{id}` as canonical for read/update and `{webhook_url_id}` as spec-exposed delete variant.
  - Phase 1 implementation treats this as a spec inconsistency and uses one internal `webhook_id` with tolerant path mapping logic (covered in `tests/test_emailbison_client.py`).
- **Required params**
  - Create/update require `name`, `url`, `events[]`.
- **Key response fields**
  - `id`, `name`, `url`, `events[]`, `created_at`, `updated_at`
- **Known caveats/inconsistencies**
  - Event list includes many event types (delivery/reply/account/tag/warmup), but API spec lookup does not expose inbound signature verification mechanics for receiving webhooks on your side.
  - MCP discovery shows additional webhook helper tools (`get_webhook_event_types`, `get_sample_webhook_payload`, `send_test_webhook_event`) that should be queried during implementation hardening.
  - **Inbound webhook signature contract (live-source verification, current state):**
    - `header name`: **not documented** in `user-emailbison` resources/spec.
    - `algorithm`: **not documented** in `user-emailbison` resources/spec.
    - `canonical payload rules`: **not documented** in `user-emailbison` resources/spec.
    - `timestamp/replay expectations`: **not documented** in `user-emailbison` resources/spec.
  - Verification evidence: direct live checks of `/api/webhook-url`, `/api/webhook-events/sample-payload`, `/api/webhook-events/test-event`, plus keyword scans (`webhook signature`, `X-Signature`, `webhook header`, `timestamp`, `replay attack`, `hmac`, `secret`) returned no webhook-signature contract details.
- **Confidence**: **Medium**

### Analytics

- **Endpoints / Tools**
  - API endpoints:
    - `POST /api/campaigns/{campaign_id}/stats`
    - `GET /api/campaign-events/stats` (requires `start_date`, `end_date`)
    - `GET /api/workspaces/v1.1/stats` (requires `start_date`, `end_date`)
  - MCP aggregate tools:
    - `user-emailbison-get_leads_analytics`
    - `user-emailbison-get_replies_analytics`
    - `user-emailbison-get_campaign_analytics`
- **Required params**
  - Date-bounded stats require `start_date` and `end_date`.
  - MCP analytics tools use simplified args (e.g., `campaign_id`, `days`, `include_samples`).
- **Key response fields**
  - Common: sent/open/reply/bounce/unsubscribe/interested counts and percentages.
  - Campaign stats can include `sequence_step_stats`.
- **Known caveats/inconsistencies**
  - API stats schemas often represent numerics as strings.
  - Mixed API-level analytics and MCP-computed analytics should be treated as separate contract layers.
- **Confidence**: **High**

### Workspace

- **Endpoints / Tools**
  - `GET /api/users` (account + team/workspace context)
  - `GET /api/workspaces/v1.1/stats`
  - `GET/PATCH /api/workspaces/v1.1/master-inbox-settings`
  - MCP workspace controls (discovered): list/switch/create workspace, token creation, invitation flows.
- **Required params**
  - Workspace stats require `start_date`, `end_date`.
  - Master inbox settings patch fields are optional booleans.
- **Key response fields**
  - User/team: team limits and flags (`sender_email_limit`, `warmup_limit`, feature flags).
  - Inbox settings: `sync_all_emails`, `smart_warmup_filter`, `auto_interested_categorization`.
- **Known caveats/inconsistencies**
  - Many workspace operations are available as extended tools but need endpoint-by-endpoint lookup before direct API calls.
- **Confidence**: **Medium**

## 3) Integration Readiness Assessment (Outbound Engine X)

## Mapping to `email_outreach` abstraction

- Existing `email_outreach` flow in this repo is currently hardwired to Smartlead in `src/routers/campaigns.py` (`_get_smartlead_entitlement`, `_get_org_smartlead_api_key`, Smartlead client imports).
- EmailBison should be integrated as an alternate provider behind the same capability:
  - keep client-facing capability as `email_outreach`
  - route to provider-specific adapter (`smartlead` vs `emailbison`) based on `company_entitlements.provider_id`.

## Alignment with existing provider patterns

- Pattern already exists for multi-provider capability split:
  - email path currently Smartlead-centric (`src/providers/smartlead/client.py`, `src/routers/campaigns.py`)
  - LinkedIn path is HeyReach (`src/providers/heyreach/client.py`, `src/routers/linkedin_campaigns.py`)
- Reusable pattern elements:
  - provider-specific client modules under `src/providers/*/client.py`
  - provider error categorization (`retryable`, transient vs terminal)
  - local upsert of normalized campaign/lead/message rows
  - webhook dedupe in `webhook_events` via `event_key`.

## Gaps / blockers / caveats

- **Auth/scoping**
  - No hard blocker. Tenant scoping model is robust (org/company checks + `org_id` filters).
  - Gap: add `organizations.provider_configs.emailbison.api_key` convention (proposed, pending confirmation with current repo config policy) and provider resolution for `email_outreach`.
- **Webhook signature/verification**
  - Current webhook ingress supports only `/api/webhooks/smartlead` and `/api/webhooks/heyreach`.
  - Must add `/api/webhooks/emailbison` plus signature verification once EmailBison signature/header format is confirmed from live spec/resources.
- **Rate limits/retry strategy**
  - EmailBison system instructions specify `3000 req/min`.
  - Current provider clients use short exponential backoff for retryable HTTP statuses; EmailBison client must include provider-aware pacing for bulk/sync jobs (targeting below limit with jitter).
- **Idempotency keys/event identity**
  - Current webhook idempotency uses explicit event id if present else SHA256(raw body). This is compatible but needs event-key precedence rules validated against EmailBison payloads.
- **Status normalization requirements**
  - `src/domain/normalization.py` currently does not include several EmailBison-native status states (campaign + lead verification categories).
  - Need explicit mapping table for EmailBison campaign, lead, and message semantics.
- **Additional caveat**
  - Current campaign router is Smartlead-specific by function names and entitlement checks; refactor to provider-dispatch layer is required before production-grade EmailBison support.
  - Refactor impact likely extends beyond `src/routers/campaigns.py` into `src/routers/internal_provisioning.py` and analytics/read paths where provider assumptions are embedded.

## Readiness Verdict

`ready with caveats`

Rationale: no architectural dead-end exists, but provider dispatch refactor, EmailBison webhook ingress/signature contract, and normalization mapping must be completed before reliable production rollout.

Implementation gates:
- Phase 2 gate: status-write contract confirmed from live spec (`PATCH pause/resume/archive`). Remaining write-path hardening should follow this contract.
- Phase 3 gate: inbound webhook signature contract is **not yet published in current live MCP/spec outputs**; lock verification code until header/algorithm/canonicalization/replay contract is confirmed via updated live sources or vendor support.
- Phase 3 contract ticket: `SUPPORT-EMAILBISON-WEBHOOK-SIGNATURE-2026-02-16` (link pending provider submission/response)
- Non-blocking hardening alignment: expand contract tests for auth-boundary permutations and malformed provider payload normalization negatives while Phase 3 verification remains blocked.
- Endpoint coverage control: maintain `docs/EMAILBISON_IMPLEMENTED_ENDPOINT_REGISTRY.md` and keep `EMAILBISON_IMPLEMENTED_ENDPOINT_REGISTRY` + guard tests in sync for strict implementation proof.

## 4) Prioritized Implementation Plan (Phase 1 / 2 / 3)

Current rollout progress:
- Slice 1 (Leads + lead lifecycle): in progress with client bulk/update lifecycle methods, campaign-router integration updates, and strict endpoint registry/test guardrails.

### Phase 1 - Provider foundation + read paths

1. Add `src/providers/emailbison/client.py` with:
   - API-key validation
   - campaign list/create
   - lead list/create
   - replies list/get
   - sender email list
   - explicit retry + rate-limit guardrails.
2. Extend provider configuration model conventions:
   - `organizations.provider_configs.emailbison.api_key` (proposed, pending confirmation with current repo config policy)
   - optional per-company provider config fields as needed.
3. Refactor `src/routers/campaigns.py` entitlement/provider resolution:
   - generic email provider resolution for capability `email_outreach`
   - dispatch to Smartlead or EmailBison adapters.
4. Confirm and update provider-assumption touchpoints in:
   - `src/routers/internal_provisioning.py`
   - analytics/read paths that currently assume provider-specific payload/fields.

### Phase 2 - Write paths + status harmonization

1. Implement EmailBison campaign state actions and lead mutations in campaign router dispatch.
2. Add EmailBison-specific normalization mapping in `src/domain/normalization.py`.
3. Expand local persistence mapping for EmailBison payload shapes (campaigns/leads/messages).
4. Add/extend tests mirroring existing patterns in:
   - `tests/test_campaigns_endpoints.py`
   - `tests/test_inboxes_endpoint.py`
   - `tests/test_analytics_endpoint.py`
5. Standardize provider error responses across Smartlead/HeyReach/EmailBison to one API-facing shape:
   - `detail.type` = `provider_error`
   - `detail.provider`, `detail.operation`, `detail.category`, `detail.retryable`, `detail.message`
6. Add contract tests for EmailBison campaign status transitions in `tests/test_campaigns_endpoints.py`.

### Phase 3 - Webhooks + observability hardening

1. Confirm live EmailBison webhook signature contract (header, algorithm, payload canonicalization, replay/timestamp policy) from current MCP/API spec.
2. Add `/api/webhooks/emailbison` ingestion route.
3. Add signature verification implementation from canonical EmailBison webhook contract.
4. Reuse existing dedupe/replay infrastructure in `src/routers/webhooks.py`.
5. Add webhook authorization + replay tests alongside:
   - `tests/test_webhooks_endpoint.py`
   - `tests/test_webhooks_authorization_matrix.py`
6. Add provider-specific observability dimensions and error taxonomy parity.

## 5) First 5 Implementation Tasks (Repo-Specific Quick Win)

1. Create `src/providers/emailbison/client.py` using the same error/retry contract used by `smartlead`/`heyreach` clients.
2. In `src/routers/campaigns.py`, replace `_get_smartlead_entitlement` with provider-agnostic `email_outreach` resolver and provider dispatch for list/create/status/replies paths.
3. Extend `src/domain/normalization.py` with EmailBison status mappings used by campaign/lead/message upserts.
4. Add EmailBison webhook route to `src/routers/webhooks.py` with event-key dedupe and payload-to-local-state projection.
5. Add focused tests:
   - provider dispatch unit/integration coverage in `tests/test_campaigns_endpoints.py`
   - webhook ingestion + idempotency in `tests/test_webhooks_endpoint.py`.

## Explicit Non-Canonical Warning

Do not use `archive/emailbison/*` as canonical source. Use only live `user-emailbison` MCP output and current API spec/tool responses.
