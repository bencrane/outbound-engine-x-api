# LeadMagic SmartLead MCP Server Reference

> **Last Updated:** January 13, 2026  
> **MCP Server:** `smartlead-mcp-server` by LeadMagic  
> **GitHub:** https://github.com/LeadMagic/smartlead-mcp-server  
> **Purpose:** Comprehensive reference for AI agents and developers integrating with SmartLead via the LeadMagic MCP server.

---

## Table of Contents

1. [Overview](#overview)
2. [Authentication & Connection](#authentication--connection)
3. [Campaign Management Tools](#campaign-management-tools)
4. [Lead Management Tools](#lead-management-tools)
5. [Email Account Tools](#email-account-tools)
6. [Analytics & Statistics Tools](#analytics--statistics-tools)
7. [Message & Communication Tools](#message--communication-tools)
8. [Rate Limits & Constraints](#rate-limits--constraints)
9. [Error Handling](#error-handling)
10. [Common Workflows](#common-workflows)
11. [Data Structures Reference](#data-structures-reference)

---

## Overview

### What is SmartLead?

SmartLead is a cold email outreach platform that enables automated email campaigns with features like:
- Multi-step email sequences with configurable delays
- Email warmup for deliverability
- Lead management and categorization
- Analytics tracking (opens, clicks, replies, bounces)
- Master inbox for centralized reply management

### What is the LeadMagic MCP Server?

The LeadMagic MCP (Model Context Protocol) server provides a programmatic interface for AI agents to interact with SmartLead's REST API. It handles:
- API authentication
- Request formatting
- Response parsing
- Error handling with actionable messages

### Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   AI Agent /    │────▶│   LeadMagic     │────▶│   SmartLead     │
│   Cursor IDE    │     │   MCP Server    │     │   REST API      │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

### Tool Naming Convention

All tools follow the pattern: `mcp_smartlead_smartlead_{action}`

Example: `mcp_smartlead_smartlead_list_campaigns`

---

## Authentication & Connection

### Configuration

The MCP server is configured in your Cursor MCP configuration file (`.cursor/mcp.json`). Authentication uses a SmartLead API key that is stored in the server configuration.

### Verifying Connection

Test connectivity by calling the list campaigns tool:

```
mcp_smartlead_smartlead_list_campaigns()
```

**Successful Response:**
```json
{
  "id": 2610406,
  "user_id": 276870,
  "created_at": "2025-10-25T21:18:58.654Z",
  "status": "DRAFTED",
  "name": "campaign-name",
  ...
}
```

**Connection Failure Indicators:**
- `401 Unauthorized` - Invalid API key
- `ECONNREFUSED` - MCP server not running
- Timeout errors - Network connectivity issues

---

## Campaign Management Tools

### `smartlead_list_campaigns`

Retrieves all campaigns for the authenticated SmartLead account.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `status` | string | No | Filter by status: `active`, `paused`, `completed` |
| `offset` | number | No | Pagination offset |

**Example:**
```
mcp_smartlead_smartlead_list_campaigns()
```

**Response:**
```json
[
  {
    "id": 2610406,
    "user_id": 276870,
    "created_at": "2025-10-25T21:18:58.654Z",
    "updated_at": "2025-10-29T16:55:14.942Z",
    "status": "DRAFTED",
    "name": "inbound-agencies-v1",
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
    "client_id": null
  }
]
```

---

### `smartlead_get_campaign`

Retrieves detailed information about a specific campaign.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `campaign_id` | number | **Yes** | The campaign ID to retrieve |

**Example:**
```
mcp_smartlead_smartlead_get_campaign(campaign_id=2610406)
```

---

### `smartlead_create_campaign`

Creates a new campaign with specified name and optional client assignment.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `name` | string | **Yes** | Campaign name |
| `client_id` | number | No | Client ID to assign campaign to |

**Example:**
```
mcp_smartlead_smartlead_create_campaign(name="Q1 Outreach 2026")
```

---

### `smartlead_update_campaign_status`

Changes the operational status of a campaign.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `campaign_id` | number | **Yes** | Campaign ID |
| `status` | string | **Yes** | New status: `START`, `PAUSED`, or `STOPPED` |

**Status Values:**
| Value | Description |
|-------|-------------|
| `START` | Activate campaign and begin sending |
| `PAUSED` | Temporarily stop sending (can resume) |
| `STOPPED` | Permanently stop campaign |

**Example:**
```
// Start a campaign
mcp_smartlead_smartlead_update_campaign_status(campaign_id=2610406, status="START")

// Pause a campaign
mcp_smartlead_smartlead_update_campaign_status(campaign_id=2610406, status="PAUSED")
```

---

### `smartlead_update_campaign_schedule`

Configures the sending schedule for a campaign including timing, frequency, and delivery windows.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `campaign_id` | number | **Yes** | Campaign ID |
| `timezone` | string | No | Timezone (e.g., "America/New_York") |
| `days_of_the_week` | number[] | No | Days to send (1=Monday, 7=Sunday) |
| `start_hour` | string | No | Start time (e.g., "09:00") |
| `end_hour` | string | No | End time (e.g., "18:00") |
| `min_time_btw_emails` | number | No | Minimum minutes between emails |
| `max_new_leads_per_day` | number | No | Maximum new leads per day |
| `schedule_start_time` | string | No | When to start the schedule |

**Example:**
```
mcp_smartlead_smartlead_update_campaign_schedule(
  campaign_id=2610406,
  timezone="America/New_York",
  days_of_the_week=[1, 2, 3, 4, 5],
  start_hour="09:00",
  end_hour="17:00",
  min_time_btw_emails=5,
  max_new_leads_per_day=50
)
```

---

### `smartlead_update_campaign_settings`

Updates various campaign settings including tracking, personalization, and delivery options.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `campaign_id` | number | **Yes** | Campaign ID |
| `name` | string | No | Campaign name |
| `status` | string | No | Status: `active`, `paused`, `completed` |
| `settings` | object | No | Additional settings object |

**Example:**
```
mcp_smartlead_smartlead_update_campaign_settings(
  campaign_id=2610406,
  name="Updated Campaign Name"
)
```

---

### `smartlead_delete_campaign`

Permanently deletes a campaign and all associated data. **This action cannot be undone.**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `campaign_id` | number | **Yes** | Campaign ID to delete |

**Example:**
```
mcp_smartlead_smartlead_delete_campaign(campaign_id=2610406)
```

⚠️ **Warning:** This permanently removes the campaign, all leads, sequences, and statistics.

---

### `smartlead_get_campaigns_with_analytics`

Retrieves campaigns list with embedded analytics data for performance overview.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `status` | string | No | Filter: `ACTIVE`, `PAUSED`, `COMPLETED`, `DRAFT` |
| `client_id` | string | No | Filter by client ID |
| `start_date` | string | No | Analytics start date |
| `end_date` | string | No | Analytics end date |

**Example:**
```
mcp_smartlead_smartlead_get_campaigns_with_analytics(status="ACTIVE")
```

---

## Email Sequence Tools

### `smartlead_get_campaign_sequence`

Retrieves the email sequence configuration for a specific campaign.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `campaign_id` | number | **Yes** | Campaign ID |

**Example:**
```
mcp_smartlead_smartlead_get_campaign_sequence(campaign_id=2610406)
```

---

### `smartlead_save_campaign_sequence`

Creates or updates the email sequence for a campaign including follow-up emails and timing.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `campaign_id` | number | **Yes** | Campaign ID |
| `sequence` | array | **Yes** | Array of sequence step objects |

**Sequence Step Object:**
```json
{
  "seq_number": 1,
  "seq_delay_details": {
    "delay_in_days": 0
  },
  "variant_distribution_type": "MANUAL_EQUAL",
  "winning_metric_property": "REPLY_RATE",
  "seq_variants": [
    {
      "subject": "Email Subject with {{first_name}}",
      "email_body": "<div>HTML content with {{company_name}}</div>",
      "variant_label": "A"
    }
  ]
}
```

**Variant Distribution Types:**
| Value | Description |
|-------|-------------|
| `MANUAL_EQUAL` | Equal distribution across variants |
| `MANUAL_PERCENTAGE` | Custom percentage per variant |
| `AI_EQUAL` | AI-optimized equal distribution |

**Winning Metric Properties:**
| Value | Description |
|-------|-------------|
| `OPEN_RATE` | Optimize for opens |
| `CLICK_RATE` | Optimize for clicks |
| `REPLY_RATE` | Optimize for replies |
| `POSITIVE_REPLY_RATE` | Optimize for positive replies |

**Example:**
```
mcp_smartlead_smartlead_save_campaign_sequence(
  campaign_id=2610406,
  sequence=[
    {
      "seq_number": 1,
      "seq_delay_details": {"delay_in_days": 0},
      "variant_distribution_type": "MANUAL_EQUAL",
      "seq_variants": [
        {
          "subject": "Quick question about {{company_name}}",
          "email_body": "<div>Hi {{first_name}},</div><div>I noticed...</div>",
          "variant_label": "A"
        }
      ]
    },
    {
      "seq_number": 2,
      "seq_delay_details": {"delay_in_days": 3},
      "variant_distribution_type": "MANUAL_EQUAL",
      "seq_variants": [
        {
          "subject": "Re: Quick question",
          "email_body": "<div>Following up...</div>",
          "variant_label": "A"
        }
      ]
    }
  ]
)
```

**Available Merge Variables:**
- `{{first_name}}` - Lead's first name
- `{{last_name}}` - Lead's last name
- `{{email}}` - Lead's email
- `{{company_name}}` or `{{company}}` - Lead's company
- `{{title}}` - Lead's job title
- `{{phone}}` - Lead's phone number
- `{{custom_field_name}}` - Any custom field by name

---

### `smartlead_get_campaign_sequence_analytics`

Retrieves analytics data for each step in a campaign sequence to optimize performance.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `campaign_id` | number | **Yes** | Campaign ID |
| `start_date` | string | No | Analytics start date |
| `end_date` | string | No | Analytics end date |

**Example:**
```
mcp_smartlead_smartlead_get_campaign_sequence_analytics(campaign_id=2610406)
```

---

## Lead Management Tools

### `smartlead_add_leads_to_campaign`

Adds one or more leads to a specific campaign with validation and duplicate checking.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `campaign_id` | integer | **Yes** | Campaign ID (must be > 0) |
| `leads` | array | **Yes** | Array of lead objects |

**Lead Object:**
```json
{
  "email": "lead@example.com",
  "first_name": "John",
  "last_name": "Doe",
  "company": "Acme Inc",
  "title": "CEO",
  "phone": "+1234567890"
}
```

**Example:**
```
mcp_smartlead_smartlead_add_leads_to_campaign(
  campaign_id=2610406,
  leads=[
    {
      "email": "john@acme.com",
      "first_name": "John",
      "last_name": "Doe",
      "company": "Acme Inc",
      "title": "CEO"
    },
    {
      "email": "jane@startup.io",
      "first_name": "Jane",
      "last_name": "Smith",
      "company": "Startup.io"
    }
  ]
)
```

---

### `smartlead_list_leads_by_campaign`

Retrieves all leads associated with a specific campaign, with optional filtering and pagination.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `campaign_id` | integer | **Yes** | Campaign ID (must be > 0) |
| `offset` | integer | No | Pagination offset (minimum: 0) |
| `limit` | integer | No | Results per page (1-1000) |
| `status` | string | No | Filter by lead status |
| `search` | string | No | Search query |

**Example:**
```
mcp_smartlead_smartlead_list_leads_by_campaign(
  campaign_id=2610406,
  offset=0,
  limit=100
)
```

---

### `smartlead_fetch_lead_by_email`

Find and retrieve lead information using their email address.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `email` | string | **Yes** | Email address (must be valid format) |

**Example:**
```
mcp_smartlead_smartlead_fetch_lead_by_email(email="john@acme.com")
```

---

### `smartlead_update_lead_by_id`

Update lead information using the lead ID, including contact details and custom fields.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `lead_id` | integer | **Yes** | Lead ID (must be > 0) |
| `email` | string | No | Updated email address |
| `first_name` | string | No | Updated first name |
| `last_name` | string | No | Updated last name |
| `company` | string | No | Updated company name |
| `title` | string | No | Updated job title |
| `phone` | string | No | Updated phone number |

**Example:**
```
mcp_smartlead_smartlead_update_lead_by_id(
  lead_id=12345,
  first_name="Jonathan",
  company="Acme Corporation"
)
```

---

### `smartlead_update_lead_category`

Update the category classification of a lead within a specific campaign.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `campaign_id` | integer | **Yes** | Campaign ID |
| `lead_id` | integer | **Yes** | Lead ID |
| `category` | string | **Yes** | New category name |

**Example:**
```
mcp_smartlead_smartlead_update_lead_category(
  campaign_id=2610406,
  lead_id=12345,
  category="Interested"
)
```

---

### `smartlead_pause_lead_by_campaign`

Pause email sending to a lead within a specific campaign without removing them.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `campaign_id` | integer | **Yes** | Campaign ID |
| `lead_id` | integer | **Yes** | Lead ID |

**Example:**
```
mcp_smartlead_smartlead_pause_lead_by_campaign(campaign_id=2610406, lead_id=12345)
```

---

### `smartlead_resume_lead_by_campaign`

Resume email sending to a paused lead within a specific campaign.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `campaign_id` | integer | **Yes** | Campaign ID |
| `lead_id` | integer | **Yes** | Lead ID |

**Example:**
```
mcp_smartlead_smartlead_resume_lead_by_campaign(campaign_id=2610406, lead_id=12345)
```

---

### `smartlead_delete_lead_by_campaign`

Remove a lead from a specific campaign permanently.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `campaign_id` | integer | **Yes** | Campaign ID |
| `lead_id` | integer | **Yes** | Lead ID |

**Example:**
```
mcp_smartlead_smartlead_delete_lead_by_campaign(campaign_id=2610406, lead_id=12345)
```

---

### `smartlead_unsubscribe_lead_from_campaign`

Unsubscribe a lead from a specific campaign, stopping all future emails.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `campaign_id` | integer | **Yes** | Campaign ID |
| `lead_id` | integer | **Yes** | Lead ID |

**Example:**
```
mcp_smartlead_smartlead_unsubscribe_lead_from_campaign(campaign_id=2610406, lead_id=12345)
```

---

### `smartlead_unsubscribe_lead_from_all_campaigns`

Unsubscribe a lead from all campaigns across the entire account.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `lead_id` | integer | **Yes** | Lead ID |

**Example:**
```
mcp_smartlead_smartlead_unsubscribe_lead_from_all_campaigns(lead_id=12345)
```

---

### `smartlead_add_lead_to_global_blocklist`

Add a lead or domain to the global blocklist to prevent future contact.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `email` | string | **Yes** | Email address to blocklist |

**Example:**
```
mcp_smartlead_smartlead_add_lead_to_global_blocklist(email="donotcontact@example.com")
```

---

### `smartlead_fetch_lead_categories`

Retrieve all available lead categories for classification and filtering purposes.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| *(none)* | - | - | No parameters required |

**Example:**
```
mcp_smartlead_smartlead_fetch_lead_categories()
```

---

### `smartlead_fetch_all_leads_from_account`

Retrieve all leads from the entire account with optional filtering and pagination.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| *(none)* | - | - | No parameters required |

**Example:**
```
mcp_smartlead_smartlead_fetch_all_leads_from_account()
```

---

### `smartlead_fetch_leads_from_global_blocklist`

Retrieve all leads and domains currently on the global blocklist.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| *(none)* | - | - | No parameters required |

**Example:**
```
mcp_smartlead_smartlead_fetch_leads_from_global_blocklist()
```

---

### `smartlead_fetch_all_campaigns_using_lead_id`

Retrieve all campaigns that contain a specific lead for cross-campaign analysis.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `lead_id` | number | **Yes** | Lead ID |

**Example:**
```
mcp_smartlead_smartlead_fetch_all_campaigns_using_lead_id(lead_id=12345)
```

---

## Email Account Tools

### `smartlead_get_all_email_accounts`

Retrieve all email accounts associated with the current user.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| *(none)* | - | - | No parameters required |

**Example:**
```
mcp_smartlead_smartlead_get_all_email_accounts()
```

**Response:**
```json
[
  {
    "id": 101,
    "email": "sender@domain.com",
    "name": "Sales Outreach",
    "smtp_host": "smtp.gmail.com",
    "smtp_port": 587,
    "warmup_enabled": true,
    "warmup_reputation": 85
  }
]
```

---

### `smartlead_get_email_account_by_id`

Retrieve detailed information about a specific email account.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `email_account_id` | integer | **Yes** | Email account ID |

**Example:**
```
mcp_smartlead_smartlead_get_email_account_by_id(email_account_id=101)
```

---

### `smartlead_create_email_account`

Create a new email account with SMTP and IMAP configuration.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `email` | string | **Yes** | Email address |
| `password` | string | **Yes** | Email password or app password |
| `smtp_host` | string | **Yes** | SMTP server hostname |
| `smtp_port` | integer | **Yes** | SMTP server port |
| `imap_host` | string | **Yes** | IMAP server hostname |
| `imap_port` | integer | **Yes** | IMAP server port |
| `name` | string | No | Display name for the account |

**Example:**
```
mcp_smartlead_smartlead_create_email_account(
  email="outreach@company.com",
  password="app-specific-password",
  smtp_host="smtp.gmail.com",
  smtp_port=587,
  imap_host="imap.gmail.com",
  imap_port=993,
  name="Sales Outreach Account"
)
```

---

### `smartlead_update_email_account`

Update an existing email account configuration.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `email_account_id` | integer | **Yes** | Email account ID |
| `email` | string | No | Updated email address |
| `password` | string | No | Updated password |
| `smtp_host` | string | No | Updated SMTP host |
| `smtp_port` | integer | No | Updated SMTP port |
| `imap_host` | string | No | Updated IMAP host |
| `imap_port` | integer | No | Updated IMAP port |
| `name` | string | No | Updated display name |

**Example:**
```
mcp_smartlead_smartlead_update_email_account(
  email_account_id=101,
  name="Updated Account Name"
)
```

---

### `smartlead_update_email_account_warmup`

Configure warmup settings for an email account to improve deliverability.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `email_account_id` | integer | **Yes** | Email account ID |
| `warmup_enabled` | boolean | **Yes** | Enable/disable warmup |
| `daily_ramp_up` | integer | No | Daily email increase rate |
| `reply_rate_percentage` | number | No | Target reply rate (0-100) |
| `warmup_reputation` | number | No | Target reputation score (0-100) |

**Example:**
```
mcp_smartlead_smartlead_update_email_account_warmup(
  email_account_id=101,
  warmup_enabled=true,
  daily_ramp_up=2,
  reply_rate_percentage=30,
  warmup_reputation=80
)
```

---

### `smartlead_update_email_account_tag`

Update the tag/label for an email account for better organization.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `email_account_id` | integer | **Yes** | Email account ID |
| `tag` | string | **Yes** | Tag/label to assign |

**Example:**
```
mcp_smartlead_smartlead_update_email_account_tag(
  email_account_id=101,
  tag="sales-team"
)
```

---

### `smartlead_reconnect_failed_email_accounts`

Attempt to reconnect email accounts that have failed authentication.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `email_account_ids` | integer[] | **Yes** | Array of email account IDs |

**Example:**
```
mcp_smartlead_smartlead_reconnect_failed_email_accounts(
  email_account_ids=[101, 102, 103]
)
```

---

### `smartlead_list_email_accounts_per_campaign`

Retrieve all email accounts associated with a specific campaign.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `campaign_id` | integer | **Yes** | Campaign ID |

**Example:**
```
mcp_smartlead_smartlead_list_email_accounts_per_campaign(campaign_id=2610406)
```

---

### `smartlead_add_email_account_to_campaign`

Add an email account to a specific campaign for sending emails.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `campaign_id` | integer | **Yes** | Campaign ID |
| `email_account_id` | integer | **Yes** | Email account ID |

**Example:**
```
mcp_smartlead_smartlead_add_email_account_to_campaign(
  campaign_id=2610406,
  email_account_id=101
)
```

---

### `smartlead_remove_email_account_from_campaign`

Remove an email account from a specific campaign.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `campaign_id` | integer | **Yes** | Campaign ID |
| `email_account_id` | integer | **Yes** | Email account ID |

**Example:**
```
mcp_smartlead_smartlead_remove_email_account_from_campaign(
  campaign_id=2610406,
  email_account_id=101
)
```

---

## Analytics & Statistics Tools

### `smartlead_get_campaign_statistics`

Retrieve comprehensive statistics for a specific campaign.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `campaign_id` | integer | **Yes** | Campaign ID |

**Example:**
```
mcp_smartlead_smartlead_get_campaign_statistics(campaign_id=2610406)
```

**Response:**
```json
{
  "total_stats": "500",
  "data": [...],
  "offset": 0,
  "limit": 500
}
```

---

### `smartlead_get_campaign_top_level_analytics`

Retrieve high-level analytics overview for a campaign.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `campaign_id` | integer | **Yes** | Campaign ID |

**Example:**
```
mcp_smartlead_smartlead_get_campaign_top_level_analytics(campaign_id=2610406)
```

---

### `smartlead_get_campaign_lead_statistics`

Retrieve detailed lead statistics for a campaign.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `campaign_id` | integer | **Yes** | Campaign ID |

**Example:**
```
mcp_smartlead_smartlead_get_campaign_lead_statistics(campaign_id=2610406)
```

---

### `smartlead_get_campaign_mailbox_statistics`

Retrieve mailbox performance statistics for a campaign.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `campaign_id` | integer | **Yes** | Campaign ID |

**Example:**
```
mcp_smartlead_smartlead_get_campaign_mailbox_statistics(campaign_id=2610406)
```

---

### `smartlead_get_warmup_stats_by_email_account_id`

Retrieve warmup statistics for a specific email account.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `email_account_id` | integer | **Yes** | Email account ID |

**Example:**
```
mcp_smartlead_smartlead_get_warmup_stats_by_email_account_id(email_account_id=101)
```

---

### `smartlead_download_campaign_data`

Download campaign data in CSV or JSON format for analysis or backup.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `campaign_id` | integer | **Yes** | Campaign ID |
| `download_type` | string | **Yes** | Type: `analytics`, `leads`, `sequences`, `full`, `summary` |
| `format` | string | No | Output format: `json` (default), `csv` |
| `user_id` | string | No | User ID for filtering |

**Example:**
```
mcp_smartlead_smartlead_download_campaign_data(
  campaign_id=2610406,
  download_type="summary",
  format="json"
)
```

**Response:**
```json
{
  "format": "json",
  "data": {
    "download_type": "summary",
    "campaign_id": 2610406,
    "total_records": 150,
    "data": [...],
    "generated_at": "2026-01-13T23:18:51.515Z"
  }
}
```

---

### `smartlead_export_campaign_data`

Export campaign data in various formats (CSV, Excel, JSON) for analysis or backup purposes.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `campaign_id` | number | **Yes** | Campaign ID |
| `format` | string | No | Format: `csv`, `excel`, `json` |
| `start_date` | string | No | Export start date |
| `end_date` | string | No | Export end date |

**Example:**
```
mcp_smartlead_smartlead_export_campaign_data(
  campaign_id=2610406,
  format="csv"
)
```

---

## Message & Communication Tools

### `smartlead_fetch_lead_message_history`

Retrieve the complete message history for a lead within a specific campaign.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `campaign_id` | integer | **Yes** | Campaign ID |
| `lead_id` | integer | **Yes** | Lead ID |

**Example:**
```
mcp_smartlead_smartlead_fetch_lead_message_history(
  campaign_id=2610406,
  lead_id=12345
)
```

---

### `smartlead_reply_to_lead_from_master_inbox`

Send a reply to a lead from the master inbox with tracking and personalization.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `campaign_id` | integer | **Yes** | Campaign ID |
| `lead_id` | integer | **Yes** | Lead ID |
| `message` | string | **Yes** | Reply message content |
| `subject` | string | No | Email subject (for new thread) |

**Example:**
```
mcp_smartlead_smartlead_reply_to_lead_from_master_inbox(
  campaign_id=2610406,
  lead_id=12345,
  message="Thanks for your interest! Let me share more details..."
)
```

---

### `smartlead_forward_reply`

Forward a lead reply to another email address or team member.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `campaign_id` | integer | **Yes** | Campaign ID |
| `lead_id` | integer | **Yes** | Lead ID |
| `forward_to` | string | **Yes** | Email address to forward to |
| `message` | string | No | Additional message to include |

**Example:**
```
mcp_smartlead_smartlead_forward_reply(
  campaign_id=2610406,
  lead_id=12345,
  forward_to="sales-manager@company.com",
  message="Hot lead - needs immediate follow-up"
)
```

---

## Rate Limits & Constraints

### SmartLead API Limits

| Constraint | Limit | Notes |
|------------|-------|-------|
| API calls per minute | ~60 | Varies by plan |
| Leads per campaign | Unlimited | Plan-dependent |
| Email accounts | Plan-dependent | Check SmartLead plan |
| Sequences per campaign | 20 | Maximum steps in sequence |
| Custom fields per lead | 200 | Maximum custom fields |
| `min_time_btw_emails` | ≥ 3 minutes | Minimum delay between sends |

### Pagination Limits

| Endpoint | Default Limit | Max Limit |
|----------|---------------|-----------|
| List leads | 100 | 1000 |
| Campaign statistics | 500 | 1000 |
| Lead statistics | 100 | 100 |
| Mailbox statistics | 20 | 20 |

### Best Practices

1. **Batch Operations**: Use bulk endpoints when adding multiple leads
2. **Pagination**: Always paginate large datasets
3. **Caching**: Cache campaign/account lists that don't change frequently
4. **Rate Limiting**: Implement exponential backoff on 429 errors

---

## Error Handling

### Common Error Codes

| Code | Status | Description | Solution |
|------|--------|-------------|----------|
| `HTTP_400` | Bad Request | Invalid parameters | Check parameter types and required fields |
| `HTTP_401` | Unauthorized | Invalid API key | Verify MCP server configuration |
| `HTTP_404` | Not Found | Resource doesn't exist | Verify campaign/lead IDs |
| `HTTP_429` | Too Many Requests | Rate limited | Wait and retry with backoff |
| `HTTP_500` | Server Error | SmartLead API issue | Retry later |

### Error Response Format

```
❌ SmartLead API Error: [error message]
**Error Code:** HTTP_[code]
**Status:** [status]

🔧 **Troubleshooting:** [guidance]

💡 **Need Help?** Visit: https://github.com/LeadMagic/smartlead-mcp-server/issues
```

### Known MCP Server Quirks

Based on live testing, some tools may return unexpected errors due to MCP-to-API parameter mapping:

| Tool | Issue | Workaround |
|------|-------|------------|
| `fetch_lead_categories` | May require `leadId` | Use alternative approach |
| `fetch_all_leads_from_account` | May require `email` | Query by campaign instead |
| Some analytics endpoints | Return 404 | Use `download_campaign_data` |

---

## Common Workflows

### Workflow 1: Launch a New Campaign

```
1. Create the campaign
   smartlead_create_campaign(name="Q1 Outreach")

2. Save email sequences
   smartlead_save_campaign_sequence(campaign_id=X, sequence=[...])

3. Configure schedule
   smartlead_update_campaign_schedule(campaign_id=X, ...)

4. Add email accounts
   smartlead_add_email_account_to_campaign(campaign_id=X, email_account_id=Y)

5. Add leads
   smartlead_add_leads_to_campaign(campaign_id=X, leads=[...])

6. Activate
   smartlead_update_campaign_status(campaign_id=X, status="START")
```

### Workflow 2: Monitor Campaign Performance

```
1. Get overall statistics
   smartlead_get_campaign_statistics(campaign_id=X)

2. Download detailed data
   smartlead_download_campaign_data(campaign_id=X, download_type="analytics")

3. Check mailbox health
   smartlead_get_warmup_stats_by_email_account_id(email_account_id=Y)
```

### Workflow 3: Handle a Reply

```
1. Get message history
   smartlead_fetch_lead_message_history(campaign_id=X, lead_id=Y)

2. Categorize the lead
   smartlead_update_lead_category(campaign_id=X, lead_id=Y, category="Interested")

3. Send reply
   smartlead_reply_to_lead_from_master_inbox(campaign_id=X, lead_id=Y, message="...")

4. Optionally pause from sequence
   smartlead_pause_lead_by_campaign(campaign_id=X, lead_id=Y)
```

### Workflow 4: Clean Up Bounces

```
1. Download campaign data filtered by bounces
   smartlead_download_campaign_data(campaign_id=X, download_type="leads")

2. For each bounced lead:
   smartlead_delete_lead_by_campaign(campaign_id=X, lead_id=Y)

3. Optionally add to blocklist
   smartlead_add_lead_to_global_blocklist(email="bounced@example.com")
```

---

## Data Structures Reference

### Campaign Status Values

| Status | Description |
|--------|-------------|
| `DRAFTED` | Campaign created but not active |
| `ACTIVE` | Campaign is sending emails |
| `PAUSED` | Temporarily stopped (can resume) |
| `COMPLETED` | All sequences sent to all leads |
| `STOPPED` | Permanently stopped |

### Stop Lead Settings

| Value | Description |
|-------|-------------|
| `REPLY_TO_AN_EMAIL` | Stop when lead replies |
| `CLICK_ON_A_LINK` | Stop when lead clicks |
| `OPEN_AN_EMAIL` | Stop when lead opens |

### Campaign Object

```json
{
  "id": 2610406,
  "user_id": 276870,
  "name": "Campaign Name",
  "status": "DRAFTED",
  "created_at": "2025-10-25T21:18:58.654Z",
  "updated_at": "2025-10-29T16:55:14.942Z",
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
  "client_id": null
}
```

### Lead Object

```json
{
  "id": 12345,
  "email": "lead@example.com",
  "first_name": "John",
  "last_name": "Doe",
  "company": "Acme Inc",
  "title": "CEO",
  "phone": "+1234567890",
  "status": "active",
  "created_at": "2025-01-01T00:00:00.000Z"
}
```

### Email Account Object

```json
{
  "id": 101,
  "email": "sender@domain.com",
  "name": "Sales Outreach",
  "smtp_host": "smtp.gmail.com",
  "smtp_port": 587,
  "imap_host": "imap.gmail.com",
  "imap_port": 993,
  "warmup_enabled": true,
  "warmup_reputation": 85,
  "daily_ramp_up": 2
}
```

---

## Complete Tool Index

### Campaign Management
- `smartlead_list_campaigns` - List all campaigns
- `smartlead_get_campaign` - Get campaign details
- `smartlead_create_campaign` - Create new campaign
- `smartlead_update_campaign_status` - Change campaign status
- `smartlead_update_campaign_schedule` - Configure schedule
- `smartlead_update_campaign_settings` - Update settings
- `smartlead_delete_campaign` - Delete campaign
- `smartlead_get_campaigns_with_analytics` - List with analytics

### Email Sequences
- `smartlead_get_campaign_sequence` - Get sequence config
- `smartlead_save_campaign_sequence` - Create/update sequence
- `smartlead_get_campaign_sequence_analytics` - Sequence performance

### Lead Management
- `smartlead_add_leads_to_campaign` - Add leads
- `smartlead_list_leads_by_campaign` - List campaign leads
- `smartlead_fetch_lead_by_email` - Find lead by email
- `smartlead_update_lead_by_id` - Update lead info
- `smartlead_update_lead_category` - Change lead category
- `smartlead_pause_lead_by_campaign` - Pause lead
- `smartlead_resume_lead_by_campaign` - Resume lead
- `smartlead_delete_lead_by_campaign` - Remove lead
- `smartlead_unsubscribe_lead_from_campaign` - Unsubscribe from campaign
- `smartlead_unsubscribe_lead_from_all_campaigns` - Unsubscribe globally
- `smartlead_add_lead_to_global_blocklist` - Blocklist lead
- `smartlead_fetch_lead_categories` - Get categories
- `smartlead_fetch_all_leads_from_account` - Get all account leads
- `smartlead_fetch_leads_from_global_blocklist` - Get blocklist
- `smartlead_fetch_all_campaigns_using_lead_id` - Find lead's campaigns

### Email Accounts
- `smartlead_get_all_email_accounts` - List all accounts
- `smartlead_get_email_account_by_id` - Get account details
- `smartlead_create_email_account` - Create account
- `smartlead_update_email_account` - Update account
- `smartlead_update_email_account_warmup` - Configure warmup
- `smartlead_update_email_account_tag` - Tag account
- `smartlead_reconnect_failed_email_accounts` - Reconnect failed
- `smartlead_list_email_accounts_per_campaign` - Campaign accounts
- `smartlead_add_email_account_to_campaign` - Add to campaign
- `smartlead_remove_email_account_from_campaign` - Remove from campaign

### Analytics & Statistics
- `smartlead_get_campaign_statistics` - Campaign stats
- `smartlead_get_campaign_top_level_analytics` - Overview analytics
- `smartlead_get_campaign_lead_statistics` - Lead-level stats
- `smartlead_get_campaign_mailbox_statistics` - Mailbox stats
- `smartlead_get_warmup_stats_by_email_account_id` - Warmup stats
- `smartlead_download_campaign_data` - Download data
- `smartlead_export_campaign_data` - Export data

### Messages & Communication
- `smartlead_fetch_lead_message_history` - Get message history
- `smartlead_reply_to_lead_from_master_inbox` - Send reply
- `smartlead_forward_reply` - Forward message

---

*This document was generated from live MCP server exploration of the LeadMagic SmartLead MCP Server. Last verified: January 13, 2026.*
