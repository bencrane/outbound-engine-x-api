# Multi-Channel Provider Single-Touch Validation

Date: 2026-03-03

## Summary Verdict

Yes, orchestrated multi-channel campaigns are viable, but only with a hybrid model: direct single-touch for EmailBison and Lob, and campaign-mediated execution for HeyReach unless/until a working direct send endpoint is confirmed for your HeyReach API scope.

## EmailBison

### Single-touch capability: CONFIRMED

### Findings

- `search_api_spec` confirms `POST /api/replies/new` ("Compose new email") as a one-off send in a **new thread** with payload fields like `to_emails`, `message`, `sender_email_id`, and optional `subject` / `content_type`.
- `call_api` against the live instance (`https://app.outboundsolutions.com`) returned:
  - `POST /api/replies/new` -> `HTTP 422` when probed with invalid payload (endpoint exists and validates request body).
  - `POST /api/replies/{reply_id}/reply` with a fake reply id -> `HTTP 404` (reply endpoint is thread-based and requires an existing reply/thread context).
- `send_reply` (MCP core tool) maps to reply-thread semantics (`reply_id` required), so it is **not** appropriate as first-touch for unknown/new contacts.
- In code, `src/providers/emailbison/client.py` currently implements many campaign/lead/reply endpoints but does **not** expose `/api/replies/new` yet.

### Recommended approach for multi-channel email steps

- Use direct single-touch via `POST /api/replies/new` for orchestrator-driven email steps (no campaign enrollment needed).
- Keep campaign flows for bulk nurture programs, not per-touch orchestration.
- If you still want campaign simulation fallback, it is possible via:
  1) create campaign  
  2) create sequence step(s)  
  3) attach lead(s)  
  4) resume campaign

### Risks / Constraints

- No explicit global API rate-limit contract was found in EmailBison spec search; treat 429 as expected and use retry/backoff.
- Sender/campaign throughput constraints still apply (`daily_limit` on sender emails, campaign-level caps like `max_emails_per_day`/`max_new_leads_per_day` in campaign objects).
- Campaign-simulation fallback has higher latency/overhead (multiple API calls + provider scheduling queue) and weaker deterministic timing than direct one-off send.

## HeyReach

### Single-touch capability: WORKAROUND REQUIRED

### Findings

- Existing client assumptions in `src/providers/heyreach/client.py`:
  - `send_message` -> `POST /message/Send` (or `/message/send`)
  - `add_campaign_leads` -> `POST /campaign/AddLeadsToListV2` (or `/campaign/add-leads`)
- Live probing with a valid org HeyReach API key:
  - `GET /api/public/auth/CheckApiKey` -> `200` (key is valid).
  - `POST /api/public/Campaign/GetAll` -> `200` (campaign listing works).
  - `POST /api/public/Message/Send` and `POST /api/public/message/send` -> `404`.
  - `POST /api/public/Campaign/AddLeadsToListV2` and additional variants tested -> `404`.
- Context7 documentation retrieval was partially available but did not return a reliable direct-message endpoint contract. It did surface:
  - network/connection-check APIs like `MyNetwork/IsConnection` (verification, not sending invites),
  - and guidance that connection requests/messages are configured as **campaign sequence actions**.
- No confirmed public API endpoint was found for directly sending a LinkedIn connection invite as a single stateless call.

### Recommended approach for multi-channel LinkedIn steps

- Treat HeyReach as campaign-mediated for now:
  - pre-create minimal reusable campaigns per action type (e.g., "connection request", "message"),
  - enqueue leads into those campaigns for each orchestrated touch.
- Build a provider-capability switch in the orchestrator so LinkedIn touches can route to:
  - direct API single-touch when/if a confirmed endpoint is available for your account,
  - otherwise campaign-injection workflow.

### Risks / Constraints

- Current client endpoint mappings for HeyReach appear stale or not enabled in your current API scope (404s on message send and lead-add routes).
- LinkedIn platform safety limits are material (HeyReach help docs indicate connection-request weekly caps and auto-freeze behavior near limits).
- This creates timing uncertainty versus your engine-owned scheduler, because campaign queues and account throttling can delay execution.

## Lob

### Single-touch capability: CONFIRMED

Lob remains stateless per-piece for outbound direct mail; `create_postcard`, `create_letter`, `create_self_mailer`, and `create_check` are single-recipient, single-piece API calls with no campaign context requirement.

## Architecture Recommendation

Proceed with a **hybrid orchestrator architecture**:

- Email + direct mail touches can be engine-owned, per-recipient, per-touch API calls.
- LinkedIn should use a provider adapter that supports campaign-mediated execution until direct HeyReach single-touch endpoints are validated for your account scope.
- Add an explicit capability matrix in the orchestration layer (`direct_single_touch` vs `campaign_mediated`) so the sequence engine stays provider-agnostic while still supporting mixed execution modes.

This keeps Directive 1 viable, but schema/workflow should include LinkedIn campaign linkage and execution-state fields (not just atomic touch dispatch) to support the fallback path.
