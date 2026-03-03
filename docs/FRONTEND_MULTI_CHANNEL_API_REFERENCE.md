# Frontend Reference: Multi-Channel Campaign API

## What Changed

We added **orchestrated multi-channel campaigns** to the backend. Previously, a campaign was tied to a single provider (e.g., EmailBison for email). Now a campaign can contain a sequence of steps across different channels — email, LinkedIn, direct mail — executed in order by the engine's orchestrator.

**Existing single-channel endpoints are unchanged.** Everything the frontend already uses (`GET /api/campaigns`, `GET /api/campaigns/messages`, `POST /api/campaigns`, etc.) works identically. Multi-channel is additive.

The `GET /api/campaigns` response now includes two new fields on every campaign:
- `campaign_type`: `"single_channel"` (existing) or `"multi_channel"` (new)
- `provider_id`: now nullable — `null` for multi-channel campaigns, populated for single-channel

---

## What This Enables

A user (the org admin) can now:
1. Create a campaign that mixes email, LinkedIn, and direct mail in one sequence
2. Define steps like: "Day 0: Send email → Day 3: Send LinkedIn connection request → Day 7: Send postcard"
3. Set conditional skip rules: "If lead replied to step 1, skip step 2"
4. Add leads to the campaign
5. Activate it — the orchestrator runs the sequence automatically on a timer
6. Monitor each lead's progress through the sequence (which step they're on, status, errors)

The frontend needs to build a **campaign builder UI** for this — step-by-step sequence design with channel selection, delay configuration, and lead management.

---

## Important: How Leads Work

Leads are **inline to a campaign** — you provide lead data (email, name, company, etc.) when adding them to a specific campaign. There is no standalone "leads database" or "lead list" in this system.

The typical flow:
1. User creates a campaign
2. User defines the sequence (steps)
3. User adds leads to the campaign (paste emails, upload CSV, or manual entry — this is a frontend UX decision)
4. User activates the campaign

Later, leads might come from external sources (CRM import, intent signals, another service pushing leads via API). The backend accepts leads via the same add-leads endpoint regardless of where they originate. The frontend doesn't need to worry about lead source — just collect the data and POST it.

---

## API Endpoints

All endpoints require `Authorization: Bearer <jwt>` from the org admin login (`POST /api/auth/login`).

Base URL: `https://api.outboundengine.dev`

---

### 1. Create Multi-Channel Campaign

```
POST /api/campaigns/multi-channel
```

**Request:**
```json
{
  "campaign_type": "multi_channel",
  "company_id": "69a9ffab-d8af-4e3c-9d6a-3d2added669f",
  "name": "Q2 Multi-Touch - Nexus Labs"
}
```

- `company_id`: required for org-level admins (which client is this campaign for)
- `name`: campaign display name

**Response** (201):
```json
{
  "id": "abc123-...",
  "company_id": "69a9ffab-...",
  "provider_id": null,
  "external_campaign_id": "",
  "name": "Q2 Multi-Touch - Nexus Labs",
  "status": "DRAFTED",
  "campaign_type": "multi_channel",
  "created_by_user_id": "...",
  "created_at": "2026-03-03T...",
  "updated_at": "2026-03-03T..."
}
```

Campaign starts in `DRAFTED` status. Cannot be activated until sequence + leads are set.

---

### 2. Define Sequence Steps

```
PUT /api/campaigns/{campaign_id}/multi-channel-sequence
```

Replaces the entire sequence. Campaign must be in `DRAFTED` status.

**Request:**
```json
{
  "steps": [
    {
      "step_order": 1,
      "channel": "email",
      "action_type": "send_email",
      "delay_days": 0,
      "execution_mode": "direct_single_touch",
      "action_config": {
        "subject": "Quick question about {{company}}",
        "message": "<p>Hi {{first_name}},</p><p>...</p>",
        "sender_email_id": 42
      }
    },
    {
      "step_order": 2,
      "channel": "linkedin",
      "action_type": "send_connection_request",
      "delay_days": 3,
      "execution_mode": "campaign_mediated",
      "provider_campaign_id": "heyreach-campaign-id-here",
      "skip_if": { "event": "reply_received" },
      "action_config": {
        "message": "Hi {{first_name}}, I sent you an email about..."
      }
    },
    {
      "step_order": 3,
      "channel": "direct_mail",
      "action_type": "send_postcard",
      "delay_days": 7,
      "execution_mode": "direct_single_touch",
      "skip_if": { "event": "reply_received" },
      "action_config": {
        "description": "Q2 postcard",
        "front": "tmpl_front_abc",
        "back": "tmpl_back_xyz",
        "to": {
          "name": "{{first_name}} {{last_name}}",
          "address_line1": "{{address}}"
        }
      }
    }
  ]
}
```

**Field reference for each step:**

| Field | Type | Required | Description |
|---|---|---|---|
| `step_order` | int (>= 1) | yes | Position in sequence. Must be unique. |
| `channel` | string | yes | `"email"`, `"linkedin"`, or `"direct_mail"` |
| `action_type` | string | yes | `"send_email"`, `"send_connection_request"`, `"send_linkedin_message"`, `"send_postcard"`, `"send_letter"` |
| `delay_days` | int (>= 0) | no (default 0) | Days to wait after the previous step before executing this one. 0 = execute immediately on next orchestrator tick. |
| `execution_mode` | string | no (default `"direct_single_touch"`) | `"direct_single_touch"` for email/direct mail, `"campaign_mediated"` for LinkedIn (HeyReach). The frontend can default this based on channel. |
| `action_config` | object | yes | Channel-specific payload. See below. |
| `skip_if` | object or null | no | Conditional skip rule. See below. |
| `provider_campaign_id` | string or null | no | Only for `campaign_mediated` steps (LinkedIn). The pre-created HeyReach campaign ID to inject leads into. |

**`action_config` by channel:**

- **Email** (`send_email`): `{ "subject": "...", "message": "...", "sender_email_id": 42 }`
- **LinkedIn** (`send_connection_request` or `send_linkedin_message`): `{ "message": "..." }`
- **Direct mail** (`send_postcard`): Lob postcard payload — `{ "description": "...", "front": "...", "back": "...", "to": {...}, "from": {...} }`
- **Direct mail** (`send_letter`): Lob letter payload — `{ "description": "...", "file": "...", "to": {...}, "from": {...} }`

**`skip_if` options (all optional):**

| Rule | Meaning |
|---|---|
| `{ "event": "reply_received" }` | Skip this step if the lead has replied to any prior step |
| `{ "event": "message_received", "direction": "inbound" }` | Skip if any inbound message exists |
| `{ "lead_status": "unsubscribed" }` | Skip if lead's status matches |
| `null` | No condition — always execute |

**Response** (200): array of created steps with server-generated `id`, `provider_id`, timestamps.

**Validation errors:**
- 400 if campaign is not `DRAFTED`
- 400 if the company doesn't have an entitlement for a step's channel (e.g., no `linkedin_outreach` capability)

---

### 3. Get Sequence Steps

```
GET /api/campaigns/{campaign_id}/multi-channel-sequence
```

**Response** (200):
```json
[
  {
    "id": "step-uuid-1",
    "step_order": 1,
    "channel": "email",
    "action_type": "send_email",
    "action_config": { "subject": "...", "message": "...", "sender_email_id": 42 },
    "delay_days": 0,
    "execution_mode": "direct_single_touch",
    "skip_if": null,
    "provider_campaign_id": null,
    "provider_id": "emailbison-provider-uuid",
    "created_at": "...",
    "updated_at": "..."
  }
]
```

---

### 4. Add Leads to Campaign

```
POST /api/campaigns/{campaign_id}/multi-channel-leads
```

**Request:**
```json
{
  "leads": [
    {
      "email": "alice@example.com",
      "first_name": "Alice",
      "last_name": "Smith",
      "company": "Acme Inc",
      "title": "VP Sales"
    },
    {
      "email": "bob@example.com",
      "first_name": "Bob",
      "last_name": "Jones",
      "company": "Beta Corp",
      "title": "CTO"
    }
  ]
}
```

Each lead requires `email`. All other fields are optional but recommended (used for template variable substitution in action_config).

**Response** (200):
```json
{
  "campaign_id": "abc123-...",
  "affected": 2,
  "status": "added"
}
```

---

### 5. Activate Campaign

```
POST /api/campaigns/{campaign_id}/activate
```

No request body needed.

**What it does:**
- Validates campaign has at least 1 step and 1 lead
- Initializes a progress row for every lead at step 1
- Sets campaign status from `DRAFTED` to `ACTIVE`
- The orchestrator picks up pending leads on its next tick (runs every 60 minutes)

**Response** (200):
```json
{
  "campaign_id": "abc123-...",
  "status": "ACTIVE",
  "leads_initialized": 2,
  "first_step_order": 1,
  "first_execute_at": "2026-03-03T17:30:00+00:00"
}

```

**Validation errors:**
- 400 if campaign is not `DRAFTED`
- 400 if no sequence steps defined
- 400 if no leads added

---

### 6. View Lead Progress

**All leads:**
```
GET /api/campaigns/{campaign_id}/lead-progress
```

Optional query param: `?step_status=pending` (filter by status)

**Response** (200):
```json
[
  {
    "id": "progress-uuid",
    "lead_id": "lead-uuid",
    "current_step_order": 2,
    "step_status": "pending",
    "next_execute_at": "2026-03-06T17:30:00+00:00",
    "executed_at": "2026-03-03T17:30:05+00:00",
    "completed_at": null,
    "attempts": 0,
    "last_error": null
  }
]
```

**Single lead:**
```
GET /api/campaigns/{campaign_id}/leads/{lead_id}/progress
```

Same response shape, single object. Also includes provider ID mappings.

**`step_status` values:**

| Status | Meaning |
|---|---|
| `pending` | Waiting for `next_execute_at` to arrive |
| `executing` | Currently being processed (transient) |
| `executed` | Step completed, advancing to next |
| `skipped` | Step was skipped due to `skip_if` condition |
| `failed` | Step failed after max retries |
| `completed` | Lead has finished all steps in the sequence |

---

### 7. Set Per-Lead Step Content (AI-Generated)

```
PUT /api/campaigns/{campaign_id}/leads/{lead_id}/step-content
```

This is the key endpoint for AI-generated campaigns. After enrolling leads, the frontend sends leads to AI for personalization, then pushes the AI output here per-lead.

**Request:**
```json
{
  "steps": [
    {
      "step_order": 1,
      "action_config_override": {
        "subject": "Hey Alice, saw Acme's Series B — quick question",
        "message": "<p>Hi Alice, congrats on the raise. We help companies at your stage...</p>"
      }
    },
    {
      "step_order": 2,
      "action_config_override": {
        "message": "Hi Alice, I sent you an email about how we helped similar companies post-Series B..."
      }
    }
  ]
}
```

The `action_config_override` merges over the step template's `action_config`. Override keys win. Template-only keys (like `sender_email_id`) are preserved. This means the AI only needs to generate the personalized content (subject, message) — structural config stays on the step template.

Can be called multiple times — it upserts (updates existing, inserts new).

**Response** (200): list of `{ "step_order": 1, "action_config_override": {...} }`

**Validation errors:**
- 400 if step_order doesn't exist in the campaign's sequence
- 400 if campaign is not multi-channel

---

### 8. Get Per-Lead Step Content

```
GET /api/campaigns/{campaign_id}/leads/{lead_id}/step-content
```

Returns all per-step content overrides for a lead. Useful for previewing what the AI generated before activating.

**Response** (200):
```json
[
  {
    "step_order": 1,
    "action_config_override": {
      "subject": "Hey Alice, saw Acme's Series B — quick question",
      "message": "<p>Hi Alice, congrats on the raise...</p>"
    }
  },
  {
    "step_order": 2,
    "action_config_override": {
      "message": "Hi Alice, I sent you an email about..."
    }
  }
]
```

---

### Note: Enrolling Leads with Content in One Call

`POST /api/campaigns/{id}/multi-channel-leads` also accepts per-step content inline at enrollment time:

```json
{
  "leads": [
    {
      "email": "alice@example.com",
      "first_name": "Alice",
      "last_name": "Smith",
      "company": "Acme Inc",
      "step_content": [
        {
          "step_order": 1,
          "action_config_override": { "subject": "...", "message": "..." }
        }
      ]
    }
  ]
}
```

Use the inline approach if AI generates content before enrollment. Use the PUT endpoint if AI generates content after enrollment (async flow).

---

## Existing Endpoints (Unchanged)

These all still work identically for both single-channel and multi-channel campaigns:

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/campaigns?all_companies=true` | List all campaigns (now includes `campaign_type` field) |
| `GET` | `/api/campaigns/messages?all_companies=true&direction=inbound` | Unified inbox |
| `GET` | `/api/campaigns/{id}/replies` | Per-campaign replies |
| `GET` | `/api/campaigns/{id}/analytics/summary` | Campaign analytics |
| `GET` | `/api/auth/me` | Current user info |

---

## VoiceDrop (Ringless Voicemail) Endpoints

VoiceDrop enables ringless voicemail drops — the prospect's phone doesn't ring, the voicemail just appears. Two modes: AI voice (text-to-speech from a cloned voice) or static audio (pre-recorded file).

All require `Authorization: Bearer <jwt>`.

### Send Voicemail (one-off)

```
POST /api/voicemail/send
```

```json
{
  "company_id": "69a9ffab-...",
  "to": "7865551234",
  "from_number": "7865550001",
  "voice_clone_id": "L55l0kg8...",
  "script": "Hi {{first_name}}, this is a quick message about..."
}
```

For static audio instead of AI voice, replace `voice_clone_id`+`script` with:
```json
{
  "recording_url": "https://example.com/audio.mp3"
}
```

### Voice Clone Management

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/voicemail/voice-clones` | List all voice clones |
| `POST` | `/api/voicemail/voice-clones` | Create clone (`{ "display_name": "...", "recording_url": "..." }`) |
| `DELETE` | `/api/voicemail/voice-clones/{voice_clone_id}` | Delete a clone |
| `POST` | `/api/voicemail/voice-clones/{voice_clone_id}/preview` | Preview clone with test script |

### Sender Number Management

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/voicemail/sender-numbers` | List verified numbers |
| `POST` | `/api/voicemail/sender-numbers/verify` | Start verification (`{ "phone_number": "...", "method": "sms" }`) |
| `POST` | `/api/voicemail/sender-numbers/verify-code` | Complete verification (`{ "phone_number": "...", "code": "..." }`) |

### Other

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/voicemail/dnc` | Add to Do Not Call list (`{ "phone": "..." }`) |
| `GET` | `/api/voicemail/campaigns/{campaign_id}/reports` | Export delivered RVMs (returns CSV URL) |

### Voicemail in Multi-Channel Sequences

When defining a multi-channel sequence step for voicemail:

```json
{
  "step_order": 3,
  "channel": "voicemail",
  "action_type": "send_voicemail",
  "delay_days": 5,
  "execution_mode": "direct_single_touch",
  "action_config": {
    "voice_clone_id": "L55l0kg8...",
    "script": "Hi, this is a follow-up about...",
    "from_number": "7865550001"
  }
}
```

The lead must have a `phone` field. If missing, the step fails (non-retryable).

For static audio, use `recording_url` instead of `voice_clone_id`+`script` in `action_config`.

---

## Available Channels for Multi-Channel Sequences

| Channel | Action Types | Execution Mode | Provider |
|---|---|---|---|
| `email` | `send_email` | `direct_single_touch` | EmailBison |
| `linkedin` | `send_connection_request`, `send_linkedin_message` | `campaign_mediated` | HeyReach |
| `direct_mail` | `send_postcard`, `send_letter` | `direct_single_touch` | Lob |
| `voicemail` | `send_voicemail` | `direct_single_touch` | VoiceDrop |

---

## Suggested Frontend UX Flow

1. **Campaign list page** — show all campaigns, badge with `campaign_type` (single vs multi-channel)
2. **Create campaign** — choice between single-channel (existing flow) and multi-channel (new flow)
3. **Multi-channel builder** — step-by-step sequence designer:
   - Add step → pick channel (email / LinkedIn / direct mail / voicemail)
   - Configure step (email subject+body, LinkedIn message, postcard template, voicemail script+voice clone)
   - Set delay (days after previous step)
   - Optionally set skip condition ("skip if replied")
   - Drag to reorder steps
4. **Add leads** — manual entry, paste CSV, or bulk input. Need email + name at minimum. Phone number required if sequence includes voicemail steps.
5. **AI personalization** — send leads to AI, get back per-step content, push via `PUT /api/campaigns/{id}/leads/{lead_id}/step-content`
6. **Review & activate** — show summary, hit activate
7. **Progress dashboard** — per-campaign view showing each lead's journey through the sequence with status indicators
8. **Voicemail settings** — manage voice clones and sender numbers under a settings/configuration page

---

## Company IDs for Outbound Solutions Org

For testing, these are the companies the frontend can create campaigns for:

| Company | ID |
|---|---|
| Nexus Labs | `69a9ffab-d8af-4e3c-9d6a-3d2added669f` |
| Pinnacle Staffing | `cacb6480-260e-498f-9c56-b6b3e51aca1f` |
| Horizon Media | `483ffe06-f9cb-4249-8815-a7673b0fc02e` |

All three have entitlements for email_outreach (EmailBison), linkedin_outreach (HeyReach), direct_mail (Lob), and voicemail_drop (VoiceDrop).

Note: voicemail_drop entitlements need to be provisioned for these companies before voicemail endpoints will work. The VoiceDrop API key also needs to be set in the org's provider_configs.
