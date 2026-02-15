# SmartLead MCP Server Reference

> **Last Updated:** January 13, 2026  
> **Purpose:** Comprehensive reference for AI agents and developers working with the SmartLead MCP integration.

## Overview

The SmartLead MCP (Model Context Protocol) server provides programmatic access to SmartLead's cold email outreach platform. It enables:

- **Campaign Management**: Create, configure, and control email campaigns
- **Lead Management**: Add, update, pause, and track leads within campaigns
- **Email Sequences**: Design multi-step email sequences with delays
- **Analytics**: Access detailed statistics on opens, clicks, replies, and bounces
- **Webhooks**: Configure real-time event notifications
- **Email Account Management**: Assign and manage sending accounts

### Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   AI Agent /    │────▶│   SmartLead     │────▶│   SmartLead     │
│   Application   │     │   MCP Server    │     │   REST API      │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

The MCP server acts as a bridge between AI agents and the SmartLead REST API, handling authentication and providing a structured interface.

---

## Authentication & Connection

### How Authentication Works

The SmartLead MCP server uses **API key authentication**. The API key is configured at the MCP server level, not passed with each request. When you call MCP tools, authentication is handled automatically.

### Connection Requirements

- The MCP server must be configured in your `.cursor/mcp.json` or equivalent MCP configuration
- API key must be valid and have appropriate permissions in SmartLead
- Network access to SmartLead API endpoints is required

### Verifying Connection

Test connectivity by calling `get_campaigns`:

```
mcp_smartlead_get_campaigns()
```

A successful response confirms authentication is working.

---

## Complete Tool Reference

### Campaign Management Tools

#### `get_campaigns`

Retrieves all campaigns for the authenticated account.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `client_id` | number | No | Filter campaigns by client ID |
| `include_tags` | boolean | No | Include campaign tags in response (default: `false`) |

**Response Structure:**
```json
{
  "id": 2610406,
  "user_id": 276870,
  "created_at": "2025-10-25T21:18:58.654Z",
  "updated_at": "2025-10-29T16:55:14.942Z",
  "status": "DRAFTED",
  "name": "campaign-name",
  "track_settings": [],
  "scheduler_cron_value": null,
  "min_time_btwn_emails": 20,
  "max_leads_per_day": 100,
  "stop_lead_settings": "REPLY_TO_AN_EMAIL",
  "schedule_start_time": null,
  "enable_ai_esp_matching": false,
  "send_as_plain_text": false,
  "follow_up_percentage": 100,
  "unsubscribe_text": null,
  "parent_campaign_id": null,
  "client_id": null,
  "tags": []  // Only present when include_tags=true
}
```

**Example Usage:**
```
// Get all campaigns
mcp_smartlead_get_campaigns()

// Get campaigns with tags
mcp_smartlead_get_campaigns(include_tags=true)

// Filter by client
mcp_smartlead_get_campaigns(client_id=12345)
```

---

#### `get_campaign_by_id`

Retrieves detailed information about a specific campaign.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `id` | number | **Yes** | The campaign ID |

**Example Usage:**
```
mcp_smartlead_get_campaign_by_id(id=2610406)
```

---

#### `create_campaign`

Creates a new campaign with specified settings.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `name` | string | **Yes** | Campaign name |
| `client_id` | number | **Yes** | Client ID |
| `from_name` | string | **Yes** | Sender display name |
| `from_email` | string | **Yes** | Sender email address |
| `subject` | string | **Yes** | Email subject line |
| `body` | string | **Yes** | Email body content (HTML supported) |
| `email_account_ids` | number[] | **Yes** | Array of email account IDs to use for sending |
| `reply_to_email` | string | No | Reply-to email address |
| `timezone` | string | No | Campaign timezone (e.g., "America/New_York") |
| `schedule_days` | string[] | No | Days to send emails (e.g., ["Monday", "Tuesday"]) |
| `start_hour` | string | No | Start hour for sending (e.g., "09:00") |
| `end_hour` | string | No | End hour for sending (e.g., "18:00") |
| `min_time_btw_emails` | number | No | Minimum seconds between emails |
| `max_time_btw_emails` | number | No | Maximum seconds between emails |
| `track_opens` | boolean | No | Enable open tracking |
| `track_clicks` | boolean | No | Enable click tracking |

**Example Usage:**
```
mcp_smartlead_create_campaign(
  name="Q1 Outreach",
  client_id=12345,
  from_name="Ben Crane",
  from_email="ben@example.com",
  subject="Quick question about {{company_name}}",
  body="<div>Hi {{first_name}},</div><div>...</div>",
  email_account_ids=[101, 102, 103],
  timezone="America/New_York",
  start_hour="09:00",
  end_hour="17:00",
  track_opens=true,
  track_clicks=true
)
```

---

#### `update_campaign_status`

Changes the status of a campaign.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `id` | number | **Yes** | Campaign ID |
| `status` | string | **Yes** | New status: `ACTIVE`, `PAUSED`, `COMPLETED`, or `STOPPED` |

**Status Values:**
- `ACTIVE` - Campaign is sending emails
- `PAUSED` - Campaign is temporarily stopped, can be resumed
- `COMPLETED` - Campaign has finished (all sequences sent to all leads)
- `STOPPED` - Campaign is permanently stopped

**Example Usage:**
```
// Start a campaign
mcp_smartlead_update_campaign_status(id=2610406, status="ACTIVE")

// Pause a campaign
mcp_smartlead_update_campaign_status(id=2610406, status="PAUSED")
```

---

#### `update_campaign_schedule`

Updates the sending schedule for a campaign.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `campaign_id` | number | **Yes** | Campaign ID |
| `timezone` | string | **Yes** | Timezone (e.g., "America/New_York") |
| `days_of_the_week` | number[] | **Yes** | Days to send (0=Sunday, 6=Saturday) |
| `start_hour` | string | **Yes** | Start time (e.g., "09:00") |
| `end_hour` | string | **Yes** | End time (e.g., "18:00") |
| `min_time_btw_emails` | number | **Yes** | Minimum minutes between emails (minimum: 3) |
| `max_new_leads_per_day` | number | **Yes** | Maximum new leads to start per day (minimum: 1) |
| `schedule_start_time` | string | No | When to start the schedule |

**Example Usage:**
```
mcp_smartlead_update_campaign_schedule(
  campaign_id=2610406,
  timezone="America/New_York",
  days_of_the_week=[1, 2, 3, 4, 5],  // Monday-Friday
  start_hour="09:00",
  end_hour="17:00",
  min_time_btw_emails=5,
  max_new_leads_per_day=50
)
```

---

#### `update_campaign_settings`

Updates various campaign settings including tracking, AI features, and behavior rules.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `campaign_id` | number | **Yes** | Campaign ID |
| `name` | string | No | Campaign name |
| `client_id` | number | No | Client ID |
| `track_settings` | string[] | No | Tracking settings array |
| `send_as_plain_text` | boolean | No | Send emails as plain text |
| `force_plain_text` | boolean | No | Force plain text for all emails |
| `add_unsubscribe_tag` | boolean | No | Add unsubscribe tag to emails |
| `unsubscribe_text` | string | No | Unsubscribe link text |
| `follow_up_percentage` | number | No | Percentage of leads to follow up (0-100) |
| `stop_lead_settings` | string | No | When to stop contacting leads |
| `enable_ai_esp_matching` | boolean | No | Enable AI ESP matching |
| `ai_categorisation_options` | number[] | No | AI categorization option IDs |
| `auto_pause_domain_leads_on_reply` | boolean | No | Auto-pause all leads from domain on reply |
| `bounce_autopause_threshold` | string | No | Bounce threshold for auto-pause |
| `ignore_ss_mailbox_sending_limit` | boolean | No | Ignore mailbox sending limits |
| `out_of_office_detection_settings` | object | No | Out-of-office detection settings |

**Out-of-Office Detection Settings Object:**
```json
{
  "ignoreOOOasReply": false,
  "autoCategorizeOOO": true,
  "autoReactivateOOO": true,
  "reactivateOOOwithDelay": 7
}
```

**Example Usage:**
```
mcp_smartlead_update_campaign_settings(
  campaign_id=2610406,
  track_settings=["opens", "clicks"],
  add_unsubscribe_tag=true,
  follow_up_percentage=100,
  out_of_office_detection_settings={
    "ignoreOOOasReply": false,
    "autoCategorizeOOO": true,
    "autoReactivateOOO": true,
    "reactivateOOOwithDelay": 7
  }
)
```

---

#### `update_campaign_team_member`

Assigns or removes a team member from a campaign.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `campaign_id` | number | **Yes** | Campaign ID |
| `teamMemberId` | number | **Yes** | Team member ID (use `null` to remove) |

**Example Usage:**
```
// Assign team member
mcp_smartlead_update_campaign_team_member(campaign_id=2610406, teamMemberId=789)

// Remove team member
mcp_smartlead_update_campaign_team_member(campaign_id=2610406, teamMemberId=null)
```

---

### Email Sequence Tools

#### `get_campaign_sequences`

Retrieves all email sequences for a campaign.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `campaign_id` | number | **Yes** | Campaign ID |

**Response Structure:**
```json
{
  "id": 4922613,
  "created_at": "2025-10-25T21:18:58.661Z",
  "updated_at": "2025-10-29T16:55:14.121Z",
  "email_campaign_id": 2610406,
  "seq_number": 1,
  "seq_delay_details": {
    "delayInDays": 1
  },
  "subject": "Email Subject",
  "email_body": "<div>HTML content</div>",
  "sequence_variants": null
}
```

**Example Usage:**
```
mcp_smartlead_get_campaign_sequences(campaign_id=2610406)
```

---

#### `save_campaign_sequences`

Creates or updates email sequences for a campaign.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `campaign_id` | number | **Yes** | Campaign ID |
| `sequences` | array | **Yes** | Array of sequence objects |

**Sequence Object Structure:**
```json
{
  "seq_number": 1,
  "subject": "Email Subject",
  "email_body": "<div>HTML content with {{variables}}</div>",
  "seq_delay_details": {
    "delay_in_days": 3
  }
}
```

**Example Usage:**
```
mcp_smartlead_save_campaign_sequences(
  campaign_id=2610406,
  sequences=[
    {
      "seq_number": 1,
      "subject": "Quick question about {{company_name}}",
      "email_body": "<div>Hi {{first_name}},</div><div>I noticed...</div>",
      "seq_delay_details": { "delay_in_days": 0 }
    },
    {
      "seq_number": 2,
      "subject": "Re: Quick question about {{company_name}}",
      "email_body": "<div>Following up on my previous email...</div>",
      "seq_delay_details": { "delay_in_days": 3 }
    },
    {
      "seq_number": 3,
      "subject": "Last attempt",
      "email_body": "<div>I'll keep this brief...</div>",
      "seq_delay_details": { "delay_in_days": 5 }
    }
  ]
)
```

**Available Merge Variables:**
- `{{first_name}}` - Lead's first name
- `{{last_name}}` - Lead's last name
- `{{email}}` - Lead's email
- `{{company_name}}` - Lead's company
- `{{custom_field_name}}` - Any custom field

---

### Lead Management Tools

#### `get_campaign_leads`

Retrieves leads for a campaign with pagination support.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `campaign_id` | number | **Yes** | Campaign ID |
| `offset` | number | No | Pagination offset (default: 0) |
| `limit` | number | No | Number of leads to return |

**Response Structure:**
```json
{
  "total_leads": "150",
  "data": [
    {
      "id": 12345,
      "email": "lead@example.com",
      "first_name": "John",
      "last_name": "Doe",
      "company_name": "Acme Inc",
      "status": "active",
      "created_at": "2025-01-01T00:00:00.000Z"
    }
  ],
  "offset": 0,
  "limit": 100
}
```

**Example Usage:**
```
// Get first 100 leads
mcp_smartlead_get_campaign_leads(campaign_id=2610406)

// Paginate through leads
mcp_smartlead_get_campaign_leads(campaign_id=2610406, offset=100, limit=100)
```

---

#### `add_leads_to_campaign`

Adds one or more leads to a campaign.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `campaign_id` | number | **Yes** | Campaign ID |
| `leads` | array | **Yes** | Array of lead objects |

**Lead Object Structure:**
```json
{
  "email": "lead@example.com",
  "first_name": "John",
  "last_name": "Doe",
  "company_name": "Acme Inc",
  "custom_fields": {
    "title": "CEO",
    "industry": "SaaS"
  }
}
```

**Example Usage:**
```
mcp_smartlead_add_leads_to_campaign(
  campaign_id=2610406,
  leads=[
    {
      "email": "john@acme.com",
      "first_name": "John",
      "last_name": "Doe",
      "company_name": "Acme Inc",
      "custom_fields": {
        "title": "CEO",
        "linkedin_url": "https://linkedin.com/in/johndoe"
      }
    },
    {
      "email": "jane@startup.io",
      "first_name": "Jane",
      "last_name": "Smith",
      "company_name": "Startup.io"
    }
  ]
)
```

---

#### `update_campaign_lead`

Updates information for an existing lead in a campaign.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `campaign_id` | number | **Yes** | Campaign ID |
| `lead_id` | number | **Yes** | Lead ID |
| `email` | string | **Yes** | Lead email address |
| `first_name` | string | No | Lead first name |
| `last_name` | string | No | Lead last name |
| `company_name` | string | No | Lead company name |
| `company_url` | string | No | Lead company URL |
| `phone_number` | string | No | Lead phone number |
| `website` | string | No | Lead website |
| `linkedin_profile` | string | No | Lead LinkedIn profile URL |
| `location` | string | No | Lead location |
| `custom_fields` | object | No | Custom field values (max 200) |

**Example Usage:**
```
mcp_smartlead_update_campaign_lead(
  campaign_id=2610406,
  lead_id=12345,
  email="john@acme.com",
  first_name="Jonathan",
  company_name="Acme Corporation",
  custom_fields={
    "title": "Chief Executive Officer"
  }
)
```

---

#### `pause_lead`

Pauses a lead in a campaign (stops sending emails to them).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `campaign_id` | number | **Yes** | Campaign ID |
| `lead_id` | number | **Yes** | Lead ID |

**Example Usage:**
```
mcp_smartlead_pause_lead(campaign_id=2610406, lead_id=12345)
```

---

#### `resume_lead`

Resumes a previously paused lead.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `campaign_id` | number | **Yes** | Campaign ID |
| `lead_id` | number | **Yes** | Lead ID |

**Example Usage:**
```
mcp_smartlead_resume_lead(campaign_id=2610406, lead_id=12345)
```

---

#### `delete_campaign_lead`

Permanently removes a lead from a campaign.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `campaign_id` | number | **Yes** | Campaign ID |
| `lead_id` | number | **Yes** | Lead ID |

**Example Usage:**
```
mcp_smartlead_delete_campaign_lead(campaign_id=2610406, lead_id=12345)
```

---

#### `unsubscribe_lead`

Unsubscribes a lead from a campaign.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `campaign_id` | number | **Yes** | Campaign ID |
| `lead_id` | number | **Yes** | Lead ID |

**Example Usage:**
```
mcp_smartlead_unsubscribe_lead(campaign_id=2610406, lead_id=12345)
```

---

#### `update_lead_category`

Updates a lead's category and optionally pauses them.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `campaign_id` | number | **Yes** | Campaign ID |
| `lead_id` | number | **Yes** | Lead ID |
| `category_id` | number | No | New category ID (use `null` to remove category) |
| `pause_lead` | boolean | No | Whether to pause the lead (default: `false`) |

**Example Usage:**
```
// Set category
mcp_smartlead_update_lead_category(
  campaign_id=2610406,
  lead_id=12345,
  category_id=5
)

// Set category and pause
mcp_smartlead_update_lead_category(
  campaign_id=2610406,
  lead_id=12345,
  category_id=5,
  pause_lead=true
)

// Remove category
mcp_smartlead_update_lead_category(
  campaign_id=2610406,
  lead_id=12345,
  category_id=null
)
```

---

#### `mark_lead_as_complete`

Manually marks a lead as complete in a campaign.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `campaign_id` | number | **Yes** | Campaign ID |
| `lead_map_id` | number | **Yes** | Lead map ID |

**Example Usage:**
```
mcp_smartlead_mark_lead_as_complete(campaign_id=2610406, lead_map_id=67890)
```

---

#### `update_lead_email_account`

Changes the email account assigned to send emails to a lead.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `email_campaign_id` | number | **Yes** | Campaign ID |
| `email_lead_id` | number | **Yes** | Lead ID |
| `email_account_id` | number | **Yes** | New email account ID |

**Example Usage:**
```
mcp_smartlead_update_lead_email_account(
  email_campaign_id=2610406,
  email_lead_id=12345,
  email_account_id=101
)
```

---

#### `export_campaign_leads`

Exports all leads from a campaign to a downloadable file.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `campaign_id` | number | **Yes** | Campaign ID |

**Example Usage:**
```
mcp_smartlead_export_campaign_leads(campaign_id=2610406)
```

---

### Statistics & Analytics Tools

#### `get_campaign_stats`

Retrieves detailed campaign statistics including email performance metrics.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `campaign_id` | number | **Yes** | Campaign ID |
| `offset` | number | No | Pagination offset |
| `limit` | number | No | Number of results (max 1000) |
| `email_sequence_number` | number | No | Filter by sequence number (1-20) |
| `email_status` | string | No | Filter by status: `opened`, `clicked`, `replied`, `unsubscribed`, `bounced` |
| `sent_time_start_date` | string | No | Start date for sent time filter |
| `sent_time_end_date` | string | No | End date for sent time filter |

**Response Structure:**
```json
{
  "total_stats": "500",
  "data": [
    {
      "lead_id": 12345,
      "email": "lead@example.com",
      "sent_at": "2025-01-01T10:00:00.000Z",
      "opened": true,
      "clicked": false,
      "replied": false,
      "bounced": false
    }
  ],
  "offset": 0,
  "limit": 500
}
```

**Example Usage:**
```
// Get all stats
mcp_smartlead_get_campaign_stats(campaign_id=2610406)

// Filter by status
mcp_smartlead_get_campaign_stats(
  campaign_id=2610406,
  email_status="replied"
)

// Filter by date range
mcp_smartlead_get_campaign_stats(
  campaign_id=2610406,
  sent_time_start_date="2025-01-01",
  sent_time_end_date="2025-01-31"
)

// Filter by sequence
mcp_smartlead_get_campaign_stats(
  campaign_id=2610406,
  email_sequence_number=1
)
```

---

#### `get_campaign_variant_statistics`

Retrieves A/B test variant performance statistics.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `campaign_id` | number | **Yes** | Campaign ID |
| `client_id` | number | No | Optional client ID filter |

**Response Structure:**
```json
{
  "ok": true,
  "data": [
    {
      "variant_id": "A",
      "sent": 100,
      "opened": 45,
      "clicked": 12,
      "replied": 8,
      "open_rate": 0.45,
      "click_rate": 0.12,
      "reply_rate": 0.08
    }
  ]
}
```

**Example Usage:**
```
mcp_smartlead_get_campaign_variant_statistics(campaign_id=2610406)
```

---

#### `get_campaign_lead_statistics`

Retrieves lead-level engagement metrics.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `campaign_id` | number | **Yes** | Campaign ID |
| `offset` | number | No | Pagination offset |
| `limit` | number | No | Number of results (max 100) |
| `event_time_gt` | string | No | Filter leads with events after this time |

**Response Structure:**
```json
{
  "hasMore": true,
  "data": [
    {
      "lead_id": 12345,
      "email": "lead@example.com",
      "opens": 3,
      "clicks": 1,
      "replies": 1,
      "last_activity": "2025-01-05T14:30:00.000Z"
    }
  ],
  "skip": 0,
  "limit": 100
}
```

**Example Usage:**
```
// Get lead statistics
mcp_smartlead_get_campaign_lead_statistics(campaign_id=2610406)

// Filter by recent activity
mcp_smartlead_get_campaign_lead_statistics(
  campaign_id=2610406,
  event_time_gt="2025-01-01T00:00:00.000Z"
)
```

---

#### `get_campaign_mailbox_statistics`

Retrieves mailbox-level performance statistics.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `campaign_id` | number | **Yes** | Campaign ID |
| `client_id` | number | No | Optional client ID filter |
| `offset` | number | No | Pagination offset |
| `limit` | number | No | Number of results (max 20) |
| `start_date` | string | No | Start date for statistics |
| `end_date` | string | No | End date for statistics |
| `time_zone` | string | No | Timezone for date calculations |

**Response Structure:**
```json
{
  "ok": true,
  "data": [
    {
      "email_account_id": 101,
      "email": "sender@domain.com",
      "sent": 150,
      "delivered": 145,
      "bounced": 5,
      "opened": 60,
      "clicked": 15,
      "replied": 10
    }
  ]
}
```

**Example Usage:**
```
mcp_smartlead_get_campaign_mailbox_statistics(
  campaign_id=2610406,
  start_date="2025-01-01",
  end_date="2025-01-31",
  time_zone="America/New_York"
)
```

---

### Message History Tools

#### `get_campaign_lead_message_history`

Retrieves complete message history for a specific lead.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `campaign_id` | number | **Yes** | Campaign ID |
| `lead_id` | number | **Yes** | Lead ID |
| `event_time_gt` | string | No | Filter events after this time |
| `show_plain_text_response` | boolean | No | Show plain text version of emails |

**Example Usage:**
```
mcp_smartlead_get_campaign_lead_message_history(
  campaign_id=2610406,
  lead_id=12345
)

// With plain text
mcp_smartlead_get_campaign_lead_message_history(
  campaign_id=2610406,
  lead_id=12345,
  show_plain_text_response=true
)
```

---

#### `get_campaign_leads_history`

Retrieves message history for multiple leads at once.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `campaign_id` | number | **Yes** | Campaign ID |
| `lead_ids` | number[] | No | Array of lead IDs (omit to get all) |
| `event_time_gt` | string | No | Filter events after this time |

**Example Usage:**
```
// Get history for specific leads
mcp_smartlead_get_campaign_leads_history(
  campaign_id=2610406,
  lead_ids=[12345, 12346, 12347]
)

// Get all recent history
mcp_smartlead_get_campaign_leads_history(
  campaign_id=2610406,
  event_time_gt="2025-01-01T00:00:00.000Z"
)
```

---

### Email Sending Tools

#### `send_campaign_email_thread`

Sends a reply email in an existing email thread.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `campaign_id` | number | **Yes** | Campaign ID |
| `email_stats_id` | string | **Yes** | Email statistics ID |
| `email_body` | string | **Yes** | Email body content |
| `to_email` | string | No | Recipient email address |
| `to_first_name` | string | No | Recipient first name |
| `to_last_name` | string | No | Recipient last name |
| `cc` | string | No | CC recipients |
| `bcc` | string | No | BCC recipients |
| `reply_message_id` | string | No | Message ID being replied to |
| `reply_email_body` | string | No | Body of email being replied to |
| `reply_email_time` | string | No | Time of email being replied to |
| `add_signature` | boolean | No | Whether to add email signature |
| `seq_type` | string | No | Sequence type |
| `schedule_condition` | string | No | Scheduling condition |
| `scheduled_time` | string | No | When to send the email |
| `attachments` | array | No | Email attachments |

**Attachment Object Structure:**
```json
{
  "file_url": "https://example.com/file.pdf",
  "file_name": "document.pdf",
  "file_type": "application/pdf",
  "file_size": 1024
}
```

**Example Usage:**
```
mcp_smartlead_send_campaign_email_thread(
  campaign_id=2610406,
  email_stats_id="stat_12345",
  email_body="<div>Thanks for your reply! Let me address your questions...</div>",
  add_signature=true
)
```

---

#### `forward_campaign_email`

Forwards an email from a campaign to other recipients.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `campaign_id` | number | **Yes** | Campaign ID |
| `message_id` | string | **Yes** | Message ID to forward |
| `stats_id` | string | **Yes** | Email statistics ID |
| `to_emails` | string | **Yes** | Comma-separated list of recipient emails |

**Example Usage:**
```
mcp_smartlead_forward_campaign_email(
  campaign_id=2610406,
  message_id="msg_12345",
  stats_id="stat_12345",
  to_emails="team@example.com,manager@example.com"
)
```

---

### Email Account Tools

#### `add_email_accounts_to_campaign`

Adds email accounts to a campaign for sending.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `campaign_id` | number | **Yes** | Campaign ID |
| `email_account_ids` | number[] | **Yes** | Array of email account IDs to add |
| `auto_adjust_warmup` | boolean | No | Auto-adjust warmup settings |

**Example Usage:**
```
mcp_smartlead_add_email_accounts_to_campaign(
  campaign_id=2610406,
  email_account_ids=[101, 102, 103],
  auto_adjust_warmup=true
)
```

---

#### `delete_email_accounts_from_campaign`

Removes email accounts from a campaign.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `campaign_id` | number | **Yes** | Campaign ID |
| `email_account_ids` | number[] | **Yes** | Array of email account IDs to remove |

**Example Usage:**
```
mcp_smartlead_delete_email_accounts_from_campaign(
  campaign_id=2610406,
  email_account_ids=[103]
)
```

---

### Webhook Tools

#### `get_campaign_webhooks`

Retrieves all webhooks configured for a campaign.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `campaign_id` | number | **Yes** | Campaign ID |

**Response Structure:**
```json
[
  {
    "id": 12345,
    "name": "Reply Notification",
    "webhook_url": "https://example.com/webhook",
    "event_types": ["reply", "click"],
    "categories": ["interested"],
    "created_at": "2025-01-01T00:00:00.000Z"
  }
]
```

**Example Usage:**
```
mcp_smartlead_get_campaign_webhooks(campaign_id=2610406)
```

---

#### `save_campaign_webhook`

Creates or updates a webhook for a campaign.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `campaign_id` | number | **Yes** | Campaign ID |
| `name` | string | **Yes** | Webhook name |
| `webhook_url` | string | **Yes** | Webhook URL |
| `event_types` | string[] | **Yes** | Event types to trigger webhook |
| `id` | number | No | Webhook ID (for updates) |
| `categories` | string[] | No | Categories to filter events |

**Available Event Types:**
- `sent` - Email was sent
- `delivered` - Email was delivered
- `opened` - Email was opened
- `clicked` - Link was clicked
- `replied` - Lead replied
- `bounced` - Email bounced
- `unsubscribed` - Lead unsubscribed

**Example Usage:**
```
// Create new webhook
mcp_smartlead_save_campaign_webhook(
  campaign_id=2610406,
  name="Reply Webhook",
  webhook_url="https://example.com/api/smartlead/webhook",
  event_types=["replied", "clicked"]
)

// Update existing webhook
mcp_smartlead_save_campaign_webhook(
  campaign_id=2610406,
  id=12345,
  name="Updated Webhook",
  webhook_url="https://example.com/api/smartlead/webhook-v2",
  event_types=["replied", "clicked", "bounced"]
)
```

---

#### `delete_campaign_webhook`

Deletes a webhook from a campaign.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `campaign_id` | number | **Yes** | Campaign ID |
| `id` | number | No | Webhook ID to delete |

**Example Usage:**
```
mcp_smartlead_delete_campaign_webhook(campaign_id=2610406, id=12345)
```

---

#### `get_campaign_webhook_summary`

Retrieves webhook execution summary and statistics.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `campaign_id` | number | **Yes** | Campaign ID |
| `fromTime` | string | No | Start date in ISO format |
| `toTime` | string | No | End date in ISO format |

**Example Usage:**
```
mcp_smartlead_get_campaign_webhook_summary(
  campaign_id=2610406,
  fromTime="2025-01-01T00:00:00.000Z",
  toTime="2025-01-31T23:59:59.999Z"
)
```

---

## Rate Limits & Constraints

### Known Limits

| Endpoint | Limit | Notes |
|----------|-------|-------|
| `get_campaign_stats` | max 1000 per request | Use pagination for large datasets |
| `get_campaign_lead_statistics` | max 100 per request | Use offset/limit pagination |
| `get_campaign_mailbox_statistics` | max 20 per request | Use offset/limit pagination |
| `custom_fields` | max 200 fields | Per lead |
| `min_time_btw_emails` | minimum 3 minutes | Cannot send faster than this |
| `email_sequence_number` | 1-20 | Maximum 20 sequences per campaign |

### API Rate Limiting

SmartLead's underlying API has rate limits that the MCP server inherits. If you encounter rate limiting:

1. **Wait and retry** - Implement exponential backoff
2. **Batch operations** - Use bulk endpoints where available (e.g., `add_leads_to_campaign` accepts arrays)
3. **Cache responses** - Don't repeatedly fetch unchanged data

### Pagination Best Practices

For large datasets, always paginate:

```
// Pattern for paginating leads
offset = 0
limit = 100
all_leads = []

while True:
  response = mcp_smartlead_get_campaign_leads(
    campaign_id=2610406,
    offset=offset,
    limit=limit
  )
  all_leads.extend(response.data)
  
  if len(response.data) < limit:
    break
  
  offset += limit
```

---

## Common Workflows

### Workflow 1: Launch a New Campaign

```
1. Create campaign
   mcp_smartlead_create_campaign(...)

2. Add email sequences
   mcp_smartlead_save_campaign_sequences(campaign_id, sequences=[...])

3. Configure schedule
   mcp_smartlead_update_campaign_schedule(campaign_id, ...)

4. Add email accounts
   mcp_smartlead_add_email_accounts_to_campaign(campaign_id, email_account_ids=[...])

5. Add leads
   mcp_smartlead_add_leads_to_campaign(campaign_id, leads=[...])

6. Configure webhooks (optional)
   mcp_smartlead_save_campaign_webhook(campaign_id, ...)

7. Activate campaign
   mcp_smartlead_update_campaign_status(campaign_id, status="ACTIVE")
```

### Workflow 2: Monitor Campaign Performance

```
1. Get overall stats
   mcp_smartlead_get_campaign_stats(campaign_id)

2. Check variant performance (if using A/B testing)
   mcp_smartlead_get_campaign_variant_statistics(campaign_id)

3. Analyze mailbox performance
   mcp_smartlead_get_campaign_mailbox_statistics(campaign_id)

4. Review individual lead engagement
   mcp_smartlead_get_campaign_lead_statistics(campaign_id)
```

### Workflow 3: Handle a Reply

```
1. Get message history
   mcp_smartlead_get_campaign_lead_message_history(campaign_id, lead_id)

2. Analyze the reply content

3. Update lead category if needed
   mcp_smartlead_update_lead_category(campaign_id, lead_id, category_id=...)

4. Send reply
   mcp_smartlead_send_campaign_email_thread(campaign_id, email_stats_id, email_body)

5. Optionally pause lead from sequence
   mcp_smartlead_pause_lead(campaign_id, lead_id)
```

### Workflow 4: Clean Up Leads

```
1. Get leads with bounces
   mcp_smartlead_get_campaign_stats(campaign_id, email_status="bounced")

2. Delete bounced leads
   for lead in bounced_leads:
     mcp_smartlead_delete_campaign_lead(campaign_id, lead.id)

3. Unsubscribe requests
   mcp_smartlead_unsubscribe_lead(campaign_id, lead_id)
```

---

## Error Handling

### Common Error Patterns

| Error | Likely Cause | Solution |
|-------|-------------|----------|
| 401 Unauthorized | Invalid API key | Check MCP server configuration |
| 404 Not Found | Invalid campaign/lead ID | Verify ID exists using `get_campaigns` |
| 429 Too Many Requests | Rate limited | Wait and retry with backoff |
| 400 Bad Request | Invalid parameters | Check parameter types and required fields |

### Defensive Coding

Always verify resources exist before operating on them:

```
// Before updating a lead, verify the campaign exists
campaign = mcp_smartlead_get_campaign_by_id(id=campaign_id)
if campaign:
  mcp_smartlead_update_campaign_lead(...)
```

---

## Data Structures Reference

### Campaign Status Values

| Status | Description |
|--------|-------------|
| `DRAFTED` | Campaign created but not yet active |
| `ACTIVE` | Campaign is actively sending emails |
| `PAUSED` | Campaign temporarily stopped |
| `COMPLETED` | All sequences sent to all leads |
| `STOPPED` | Campaign permanently stopped |

### Stop Lead Settings

| Value | Description |
|-------|-------------|
| `REPLY_TO_AN_EMAIL` | Stop when lead replies to any email |
| `CLICK_ON_A_LINK` | Stop when lead clicks any link |
| `OPEN_AN_EMAIL` | Stop when lead opens any email |

### Email Status Values

| Status | Description |
|--------|-------------|
| `opened` | Lead opened the email |
| `clicked` | Lead clicked a link in the email |
| `replied` | Lead replied to the email |
| `unsubscribed` | Lead unsubscribed |
| `bounced` | Email bounced |

---

## Appendix: Field Reference

### Campaign Object Fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | number | Unique campaign identifier |
| `user_id` | number | Owner user ID |
| `name` | string | Campaign name |
| `status` | string | Current status |
| `created_at` | string | ISO timestamp |
| `updated_at` | string | ISO timestamp |
| `track_settings` | array | Tracking configuration |
| `min_time_btwn_emails` | number | Minimum minutes between sends |
| `max_leads_per_day` | number | Daily lead limit |
| `stop_lead_settings` | string | When to stop lead |
| `enable_ai_esp_matching` | boolean | AI ESP matching enabled |
| `send_as_plain_text` | boolean | Plain text mode |
| `follow_up_percentage` | number | Follow-up rate (0-100) |
| `unsubscribe_text` | string | Unsubscribe link text |
| `parent_campaign_id` | number | Parent campaign (if child) |
| `client_id` | number | Associated client ID |

### Sequence Object Fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | number | Unique sequence identifier |
| `email_campaign_id` | number | Parent campaign ID |
| `seq_number` | number | Position in sequence (1-20) |
| `subject` | string | Email subject line |
| `email_body` | string | HTML email body |
| `seq_delay_details` | object | Delay configuration |
| `sequence_variants` | array | A/B test variants |

### Lead Object Fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | number | Unique lead identifier |
| `email` | string | Lead email address |
| `first_name` | string | First name |
| `last_name` | string | Last name |
| `company_name` | string | Company name |
| `company_url` | string | Company website |
| `phone_number` | string | Phone number |
| `linkedin_profile` | string | LinkedIn URL |
| `location` | string | Location |
| `website` | string | Personal website |
| `custom_fields` | object | Custom field key-value pairs |

---

*This document was generated from live MCP server exploration and represents the complete SmartLead MCP capability set as of January 2026.*
