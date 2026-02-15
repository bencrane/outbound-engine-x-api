# HeyReach MCP Server Reference

> **Complete reference documentation for the HeyReach MCP Server**  
> Last Updated: January 2026  
> MCP Server Version: 2.0.0

## Overview

The HeyReach MCP Server is a Model Context Protocol server that provides programmatic access to HeyReach's LinkedIn automation platform. It enables AI agents and automation tools to manage LinkedIn outreach campaigns, leads, conversations, and analytics.

### What is HeyReach?

HeyReach is a LinkedIn automation and outreach platform that helps businesses:
- Run automated LinkedIn connection request campaigns
- Send personalized messages at scale
- Track engagement metrics (connection rates, reply rates)
- Manage leads across multiple campaigns
- Coordinate outreach across multiple LinkedIn accounts

### What is MCP?

The Model Context Protocol (MCP) is a standardized protocol for AI agents to interact with external tools and services. The HeyReach MCP Server implements this protocol, allowing AI assistants like Claude, ChatGPT, and automation tools like n8n to control HeyReach programmatically.

---

## Authentication & Connection

### API Key Setup

1. Log into your HeyReach account at [app.heyreach.io](https://app.heyreach.io)
2. Navigate to **Settings → API Keys**
3. Generate a new API key
4. Copy and securely store the key

**API Key Format**: Base64-encoded string (typically 40+ characters)
```
Example: f0ljLNbIytCaY4MN7GPNV20KLxwig/lKrIaeLASeri0
```

### Transport Methods

The MCP server supports two transport methods:

#### 1. Stdio Transport (Local)
Best for: Claude Desktop, Cursor IDE, local development

```bash
npx heyreach-mcp-server --api-key=YOUR_API_KEY
```

#### 2. HTTP Streaming Transport (Remote)
Best for: n8n, cloud deployments, shared access

```bash
npx heyreach-mcp-http --port=3000
```

### Authentication Headers

When using HTTP transport, authenticate via headers:

```http
POST /mcp
Headers:
  Content-Type: application/json
  Accept: application/json, text/event-stream
  X-API-Key: YOUR_API_KEY
```

Alternative authentication:
```http
Authorization: Bearer YOUR_API_KEY
```

### MCP Client Configuration

#### Claude Desktop
**macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "heyreach": {
      "command": "npx",
      "args": [
        "heyreach-mcp-server@2.0.0",
        "--api-key=YOUR_API_KEY"
      ]
    }
  }
}
```

#### Cursor IDE
```json
{
  "mcp": {
    "servers": {
      "heyreach": {
        "command": "npx",
        "args": ["heyreach-mcp-server", "--api-key=YOUR_API_KEY"]
      }
    }
  }
}
```

#### n8n (HTTP Transport)
```
Endpoint: https://your-deployment.up.railway.app/mcp
Server Transport: HTTP Streamable
Authentication: Header Auth
Credential: X-API-Key: YOUR_API_KEY
```

---

## API Base Information

| Property | Value |
|----------|-------|
| Base URL | `https://api.heyreach.io/api/public` |
| Auth Header | `X-API-KEY` |
| Content-Type | `application/json` |
| Timeout | 30 seconds |

---

## Complete Tool Reference

### Tool Availability Summary

| Tool | Status | Category |
|------|--------|----------|
| `check-api-key` | ✅ Working | Authentication |
| `get-all-campaigns` | ✅ Working | Campaign Management |
| `get-campaign-details` | ✅ Working | Campaign Management |
| `toggle-campaign-status` | ✅ Working | Campaign Management |
| `create-campaign` | ❌ Not Available | Campaign Management |
| `add-leads-to-campaign` | ✅ Working* | Lead Management |
| `get-lead` | ✅ Working | Lead Management |
| `get-all-leads` | ✅ Working | Lead Management |
| `get-leads-from-list` | ✅ Working | Lead Management |
| `get-campaign-leads` | ❌ Not Available | Lead Management |
| `update-lead-status` | ❌ Not Available | Lead Management |
| `get-all-linkedin-accounts` | ✅ Working | LinkedIn Accounts |
| `get-my-network-for-sender` | ✅ Working | LinkedIn Accounts |
| `get-all-lists` | ✅ Working | List Management |
| `create-empty-list` | ✅ Working | List Management |
| `get-companies-from-list` | ✅ Working | List Management |
| `get-conversations-v2` | ✅ Working | Conversations |
| `get-overall-stats` | ✅ Working | Analytics |
| `get-campaign-metrics` | ❌ Not Available | Analytics |
| `get-all-webhooks` | ✅ Working | Webhooks |
| `create-webhook` | ✅ Working | Webhooks |
| `get-webhook-by-id` | ✅ Working | Webhooks |
| `update-webhook` | ✅ Working | Webhooks |
| `delete-webhook` | ✅ Working | Webhooks |
| `send-message` | ❌ Not Available | Messaging |
| `get-message-templates` | ❌ Not Available | Messaging |
| `perform-social-action` | ❌ Not Available | Social Actions |

*\*Requires ACTIVE campaign with LinkedIn accounts assigned*

**Working Tools**: 19/27 (70.4%)

---

## Authentication Tools

### check-api-key

Verify that your HeyReach API key is valid and has proper permissions.

**Parameters**: None

**API Endpoint**: `GET /auth/CheckApiKey`

**Example Usage**:
```json
{
  "tool": "check-api-key",
  "arguments": {}
}
```

**Success Response**:
```json
{
  "success": true,
  "data": true,
  "message": "API key is valid (Status: 200)"
}
```

**Error Response**:
```json
{
  "success": false,
  "error": "HeyReach API Error: 401 - Invalid API key"
}
```

**Use Cases**:
- Verify integration setup before running other operations
- Troubleshoot authentication issues
- Validate API key after rotation

---

## Campaign Management Tools

### get-all-campaigns

Retrieve all campaigns from your HeyReach account.

**Parameters**: None

**API Endpoint**: `POST /campaign/GetAll`

**Example Usage**:
```json
{
  "tool": "get-all-campaigns",
  "arguments": {}
}
```

**Response**:
```json
{
  "success": true,
  "data": [
    {
      "id": 90486,
      "name": "Q1 LinkedIn Outreach",
      "status": "ACTIVE",
      "creationTime": "2025-01-24T21:30:29.037886Z",
      "campaignAccountIds": [12345, 67890]
    },
    {
      "id": 90487,
      "name": "Tech Executive Campaign",
      "status": "DRAFT",
      "creationTime": "2025-01-25T10:15:00.000000Z",
      "campaignAccountIds": []
    }
  ],
  "pagination": {
    "page": 1,
    "limit": 50,
    "total": 6,
    "hasMore": false
  }
}
```

**Campaign Status Values**:
| Status | Description |
|--------|-------------|
| `DRAFT` | Campaign created but not launched |
| `ACTIVE` | Campaign is running |
| `PAUSED` | Campaign temporarily stopped |
| `COMPLETED` | Campaign finished |
| `IN_PROGRESS` | Campaign actively sending |

**Use Cases**:
- List all campaigns before selecting one to work with
- Find campaign IDs for other operations
- Check campaign statuses across your account
- Identify which campaigns have LinkedIn accounts assigned

---

### get-campaign-details

Get detailed information about a specific campaign.

**Parameters**:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `campaignId` | string | Yes | Campaign ID from `get-all-campaigns` |

**API Endpoint**: `GET /campaign/GetById?campaignId={id}`

**Example Usage**:
```json
{
  "tool": "get-campaign-details",
  "arguments": {
    "campaignId": "90486"
  }
}
```

**Response**:
```json
{
  "success": true,
  "data": {
    "id": 90486,
    "name": "Q1 LinkedIn Outreach",
    "status": "ACTIVE",
    "description": "Targeting CTOs at Series B startups",
    "creationTime": "2025-01-24T21:30:29.037886Z",
    "campaignAccountIds": [12345, 67890],
    "leadCount": 150,
    "settings": {
      "dailyLimit": 50,
      "delayBetweenActions": 30
    }
  }
}
```

**Prerequisites**:
- Use `get-all-campaigns` first to obtain valid campaign IDs

**Use Cases**:
- Verify campaign configuration before adding leads
- Check if campaign has LinkedIn accounts assigned
- Review campaign settings and status

---

### toggle-campaign-status

Pause or resume a campaign.

**Parameters**:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `campaignId` | string | Yes | Campaign ID |
| `action` | enum | Yes | `"pause"` or `"resume"` |

**API Endpoints**:
- Pause: `POST /campaign/Pause?campaignId={id}`
- Resume: `POST /campaign/Resume?campaignId={id}`

**Example Usage - Pause**:
```json
{
  "tool": "toggle-campaign-status",
  "arguments": {
    "campaignId": "90486",
    "action": "pause"
  }
}
```

**Example Usage - Resume**:
```json
{
  "tool": "toggle-campaign-status",
  "arguments": {
    "campaignId": "90486",
    "action": "resume"
  }
}
```

**Response**:
```json
{
  "success": true,
  "data": {
    "id": "90486",
    "name": "Q1 LinkedIn Outreach",
    "status": "PAUSED",
    "updatedAt": "2025-01-26T15:30:00Z"
  }
}
```

**Use Cases**:
- Temporarily stop a campaign for review
- Resume campaigns after making adjustments
- Control campaign execution without deletion

---

### create-campaign

> ⚠️ **NOT AVAILABLE** - This endpoint does not exist in the HeyReach API.

Campaign creation must be done through the HeyReach web interface.

**Workaround**: Create campaigns manually in HeyReach, then use the API to:
1. Retrieve campaign IDs with `get-all-campaigns`
2. Add leads with `add-leads-to-campaign`
3. Control execution with `toggle-campaign-status`

---

## Lead Management Tools

### add-leads-to-campaign

Add leads to an existing campaign.

> ⚠️ **Critical Requirements**:
> - Campaign status must be `ACTIVE` or `IN_PROGRESS` (NOT `DRAFT`)
> - Campaign must have LinkedIn accounts assigned (`campaignAccountIds` not empty)
> - Campaign must be created with "Create empty list" option

**Parameters**:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `campaignId` | string | Yes | Target campaign ID |
| `leads` | array | Yes | Array of lead objects (1-1000 leads) |

**Lead Object Properties**:

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `firstName` | string | No | Lead's first name (1-50 chars) |
| `lastName` | string | No | Lead's last name (1-50 chars) |
| `email` | string | No | Valid email address |
| `linkedinUrl` | string | No | Full LinkedIn profile URL |
| `company` | string | No | Company name (1-100 chars) |
| `position` | string | No | Job title (1-100 chars) |

**API Endpoint**: `POST /campaign/AddLeadsToListV2`

**Example Usage**:
```json
{
  "tool": "add-leads-to-campaign",
  "arguments": {
    "campaignId": "90486",
    "leads": [
      {
        "firstName": "John",
        "lastName": "Smith",
        "email": "john.smith@techcorp.com",
        "linkedinUrl": "https://linkedin.com/in/johnsmith",
        "company": "TechCorp Inc",
        "position": "VP of Engineering"
      },
      {
        "firstName": "Sarah",
        "lastName": "Johnson",
        "linkedinUrl": "https://linkedin.com/in/sarahjohnson",
        "company": "StartupXYZ",
        "position": "CTO"
      }
    ]
  }
}
```

**Success Response**:
```json
{
  "success": true,
  "data": {
    "addedCount": 2
  },
  "message": "Successfully added 2 leads to campaign"
}
```

**Error Response - Draft Campaign**:
```json
{
  "success": false,
  "error": "HeyReach API Error: 400 - Campaign must be ACTIVE to add leads"
}
```

**Best Practices**:
1. Always verify campaign is ACTIVE before adding leads
2. Include LinkedIn URL for LinkedIn-based campaigns
3. Provide personalization fields (firstName, company, position) for better outreach
4. Batch leads (up to 1000 per request) for efficiency
5. Duplicate leads are automatically filtered by HeyReach

**Use Cases**:
- Import leads from CRM systems
- Add prospects from lead generation tools (Apollo, Clay)
- Sync bounced email leads for LinkedIn follow-up

---

### get-campaign-leads

> ⚠️ **NOT AVAILABLE** - This endpoint does not exist in the HeyReach API.

Lead information must be accessed through the HeyReach web interface.

---

### update-lead-status

> ⚠️ **NOT AVAILABLE** - This endpoint does not exist in the HeyReach API.

Lead status updates must be done through the HeyReach web interface.

---

## Messaging Tools

### send-message

> ⚠️ **NOT AVAILABLE** - This endpoint does not exist in the HeyReach API.

Messages must be sent through campaign automation in the HeyReach web interface.

---

### get-message-templates

> ⚠️ **NOT AVAILABLE** - This endpoint does not exist in the HeyReach API.

Templates must be managed through the HeyReach web interface.

---

## Social Action Tools

### perform-social-action

> ⚠️ **NOT AVAILABLE** - This endpoint does not exist in the HeyReach API.

Social actions (likes, follows, profile views) must be configured through campaign automation.

---

## Analytics Tools

### get-campaign-metrics

> ⚠️ **NOT AVAILABLE** - Per-campaign metrics endpoint does not exist.

Use the HeyReach web interface for campaign-specific analytics, or export data to CSV.

---

## Additional Working Endpoints

These endpoints are available in the HeyReach API but may not be exposed in all MCP implementations:

### Get Overall Stats
**Endpoint**: `POST /stats/GetOverallStats`

Returns comprehensive analytics across all campaigns.

**Example Response**:
```json
{
  "totalLeads": 5000,
  "totalContacted": 3500,
  "totalReplied": 450,
  "totalConnected": 1200,
  "overallResponseRate": 12.8,
  "overallConnectionRate": 34.3
}
```

### Get Conversations
**Endpoint**: `POST /inbox/GetConversationsV2`

Retrieve LinkedIn conversations with advanced filtering.

**Parameters**:
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `filters` | object | Yes | Filter criteria |
| `limit` | integer | No | Results per page (default: 10) |
| `offset` | integer | No | Pagination offset |

**Filter Options**:
```json
{
  "filters": {
    "campaignIds": [123, 456],
    "senderIds": [789],
    "hasUnread": true,
    "keyword": "interested"
  },
  "limit": 20,
  "offset": 0
}
```

### Get All Lists
**Endpoint**: `POST /list/GetAll`

Retrieve all lead lists with pagination.

**Parameters**:
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | integer | 10 | Results per page |
| `offset` | integer | 0 | Pagination offset |

### Create Empty List
**Endpoint**: `POST /list/CreateEmptyList`

Create new lead or company lists.

**Parameters**:
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `name` | string | Yes | List name |
| `type` | string | No | `USER_LIST` (leads) or `COMPANY_LIST` |

### Get Lead Details
**Endpoint**: `POST /lead/GetLead`

Get detailed information about a specific lead by LinkedIn profile URL.

**Parameters**:
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `profileUrl` | string | Yes | LinkedIn profile URL |

### Get All Leads from List
**Endpoint**: `POST /list/GetLeads` (alternative path)

Get paginated list of leads from a specific list.

**Parameters**:
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `listId` | integer | Yes | List ID |
| `limit` | integer | No | Results per page (default: 100) |
| `offset` | integer | No | Pagination offset |
| `keyword` | string | No | Search filter |
| `leadProfileUrl` | string | No | Filter by LinkedIn URL |
| `createdFrom` | string | No | ISO date filter |
| `createdTo` | string | No | ISO date filter |

### Get Companies from List
**Endpoint**: `POST /list/GetCompanies`

Get paginated list of companies from a company list.

**Parameters**:
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `listId` | integer | Yes | Company list ID |
| `limit` | integer | No | Results per page (default: 10) |
| `offset` | integer | No | Pagination offset |
| `keyword` | string | No | Search filter |

---

## Webhook Management

HeyReach supports webhooks for real-time event notifications.

### Get All Webhooks
**Endpoint**: `POST /webhook/GetAll`

**Parameters**:
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | integer | 100 | Results per page |
| `offset` | integer | 0 | Pagination offset |

### Create Webhook
**Endpoint**: `POST /webhook/Create`

**Parameters**:
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `webhookName` | string | Yes | Webhook name |
| `webhookUrl` | string | Yes | Callback URL |
| `eventType` | string | Yes | Event type (see below) |
| `campaignIds` | array | No | Filter by campaigns |

**Event Types**:
- `LEAD_REPLIED` - Lead responded to message
- `CONNECTION_ACCEPTED` - Connection request accepted
- `MESSAGE_SENT` - Message was sent
- `PROFILE_VIEWED` - Profile was viewed
- `LEAD_ADDED` - Lead added to campaign

**Example Request**:
```json
{
  "webhookName": "Lead Replies Webhook",
  "webhookUrl": "https://your-app.com/webhooks/heyreach",
  "eventType": "LEAD_REPLIED",
  "campaignIds": [123, 456]
}
```

### Get Webhook by ID
**Endpoint**: `GET /webhook/GetById?webhookId={id}`

### Update Webhook
**Endpoint**: `POST /webhook/Update`

**Parameters**:
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `webhookId` | string | Yes | Webhook ID |
| `webhookName` | string | No | New name |
| `webhookUrl` | string | No | New URL |
| `eventType` | string | No | New event type |
| `campaignIds` | array | No | New campaign filter |
| `isActive` | boolean | No | Enable/disable |

### Delete Webhook
**Endpoint**: `POST /webhook/Delete`

**Parameters**:
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `webhookId` | string | Yes | Webhook ID to delete |

---

## Rate Limits & Constraints

### API Rate Limits

HeyReach enforces rate limits to protect LinkedIn account safety:

| Limit Type | Value | Notes |
|------------|-------|-------|
| API Requests | ~100/minute | General API throttling |
| Leads per Request | 1,000 max | `add-leads-to-campaign` batch limit |
| Daily Actions | Varies | Based on LinkedIn account settings |

### LinkedIn Safety Limits

These limits are enforced by HeyReach to protect your LinkedIn accounts:

| Action | Recommended Daily Limit |
|--------|------------------------|
| Connection Requests | 20-50 per account |
| Messages | 50-100 per account |
| Profile Views | 100-150 per account |

### Campaign Constraints

| Constraint | Value |
|------------|-------|
| Max campaigns | Unlimited |
| Max leads per campaign | Unlimited |
| Min delay between actions | 5 minutes |
| Working hours | Configurable per campaign |

---

## Error Handling

### Common Error Codes

| Code | Meaning | Solution |
|------|---------|----------|
| 400 | Bad Request | Check request payload format |
| 401 | Unauthorized | Invalid or expired API key |
| 403 | Forbidden | API key lacks required permissions |
| 404 | Not Found | Endpoint doesn't exist or resource missing |
| 422 | Unprocessable Entity | Invalid data (duplicate leads, bad URLs) |
| 429 | Rate Limited | Slow down requests |
| 500 | Server Error | Retry after delay |

### Error Response Format

```json
{
  "success": false,
  "error": "HeyReach API Error: 400 - Campaign must be ACTIVE to add leads"
}
```

### Troubleshooting Guide

**"Invalid API key"**
- Verify API key is correct and not expired
- Check for extra whitespace or encoding issues
- Generate a new key if problem persists

**"Campaign must be ACTIVE"**
- Launch the campaign in HeyReach web interface
- Ensure LinkedIn accounts are assigned to campaign
- Campaign status must not be DRAFT

**"404 Not Found" on endpoint**
- Endpoint may not exist in HeyReach API
- Check this documentation for endpoint availability
- Use HeyReach web interface for unavailable features

---

## Workflow Examples

### Example 1: Basic Campaign Check

```
1. check-api-key → Verify authentication
2. get-all-campaigns → List available campaigns
3. get-campaign-details → Review specific campaign
```

### Example 2: Add Leads to Running Campaign

```
1. get-all-campaigns → Find ACTIVE campaign with LinkedIn accounts
2. Verify: status = "ACTIVE" AND campaignAccountIds.length > 0
3. add-leads-to-campaign → Add leads to the campaign
```

### Example 3: Pause Campaign for Review

```
1. get-all-campaigns → Find target campaign
2. toggle-campaign-status → action: "pause"
3. (Review campaign in web interface)
4. toggle-campaign-status → action: "resume"
```

---

## Integration Patterns

### With n8n Automation

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   Trigger   │────▶│  HeyReach    │────▶│   Action    │
│  (Webhook)  │     │  MCP Client  │     │  (Notify)   │
└─────────────┘     └──────────────┘     └─────────────┘
```

### With Clay Data Enrichment

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│    Clay     │────▶│  HeyReach    │────▶│  Campaign   │
│  (Leads)    │     │  API Call    │     │  (Active)   │
└─────────────┘     └──────────────┘     └─────────────┘
```

### With Smartlead Email Bounces

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│  Smartlead  │────▶│   Make.com   │────▶│  HeyReach   │
│  (Bounces)  │     │  (Webhook)   │     │  (LinkedIn) │
└─────────────┘     └──────────────┘     └─────────────┘
```

---

## Changelog

### v2.0.0 (Current)
- HTTP Streaming Transport support
- Header-based authentication
- Cloud deployment ready (Vercel, Railway, Docker)
- Session management for HTTP transport

### v1.2.3
- n8n Agent compatibility
- Environment variable support for API keys
- Enhanced error handling

### v1.1.6
- 91.7% tool success rate
- Campaign status validation
- `get-active-campaigns` tool added

---

## Resources

- **HeyReach Platform**: [app.heyreach.io](https://app.heyreach.io)
- **HeyReach Help Center**: [help.heyreach.io](https://help.heyreach.io)
- **MCP Server GitHub**: [github.com/bcharleson/heyreach-mcp](https://github.com/bcharleson/heyreach-mcp)
- **MCP Specification**: [spec.modelcontextprotocol.io](https://spec.modelcontextprotocol.io)
- **API Documentation (Postman)**: [documenter.getpostman.com/view/23808049/2sA2xb5F75](https://documenter.getpostman.com/view/23808049/2sA2xb5F75)

---

## LinkedIn Account Management

> ⚠️ **Important**: LinkedIn accounts cannot be connected via API. They must be connected through the HeyReach web interface using one of these methods:
> 1. **LinkedIn Credentials** - Enter email/password (preferred, allows auto-relogin)
> 2. **HeyReach Login Extension** - Browser extension for secure auth

### Available LinkedIn Account Endpoints

#### Get All LinkedIn Accounts

Retrieve all connected LinkedIn accounts (senders) in your HeyReach account.

**Endpoint**: `POST /linkedinaccount/GetAll`

**Parameters**:
| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `keyword` | string | No | - | Search filter |
| `limit` | integer | No | 10 | Results per page (1-100) |
| `offset` | integer | No | 0 | Pagination offset |

**Example Request**:
```json
{
  "keyword": "",
  "limit": 10,
  "offset": 0
}
```

**Example Response**:
```json
{
  "items": [
    {
      "id": 12345,
      "name": "John Smith",
      "linkedinUrl": "https://linkedin.com/in/johnsmith",
      "status": "AVAILABLE",
      "subscriptionType": "SALES_NAVIGATOR"
    }
  ],
  "totalCount": 5
}
```

**LinkedIn Account Status Values**:
| Status | Description |
|--------|-------------|
| `AVAILABLE` | Account connected and ready to use |
| `RECONNECT_NEEDED` | Session expired, needs re-authentication |
| `PENDING` | Connection in progress |
| `RESTRICTED` | LinkedIn has restricted the account |

### Get My Network for Sender

Retrieve the LinkedIn connections for a specific sender account.

**Endpoint**: `POST /MyNetwork/GetMyNetworkForSender`

**Parameters**:
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `senderId` | integer | Yes | LinkedIn account ID |
| `pageNumber` | integer | Yes | Page number (1-based) |
| `pageSize` | integer | Yes | Results per page |

**Example Request**:
```json
{
  "senderId": 12345,
  "pageNumber": 1,
  "pageSize": 50
}
```

### Sender Rotation (Multiple LinkedIn Accounts)

HeyReach supports assigning multiple LinkedIn senders to a single campaign for scalable outreach:

1. **Connect multiple LinkedIn accounts** in the HeyReach web interface
2. **Select multiple senders** when creating/editing a campaign
3. **Leads are auto-rotated** across selected senders
4. **Daily limits are per-sender** and shared across campaigns

**Key Concepts**:
- Each LinkedIn account can be assigned to multiple campaigns
- Daily action limits (20-50 connections/day) are per LinkedIn account
- All conversations from all senders appear in unified Unibox
- One person can manage 10+ LinkedIn inboxes from one interface

### Assigning LinkedIn Accounts to Campaigns

When adding leads via API, you can optionally specify which LinkedIn sender to use:

**In Clay Integration**:
- Leave LinkedIn account field empty → Auto-assign to any active sender
- Select specific sender → Leads assigned to that sender only

**In API Calls** (when supported):
- `linkedInAccountId` parameter in message/conversation endpoints
- `senderId` parameter for network operations

---

## Appendix: API Endpoint Status

| Endpoint | Method | Status | Notes |
|----------|--------|--------|-------|
| `/auth/CheckApiKey` | GET | ✅ Working | API key validation |
| `/campaign/GetAll` | POST | ✅ Working | Returns campaign list |
| `/campaign/GetById` | GET | ✅ Working | Query param: `?campaignId={id}` |
| `/campaign/Pause` | POST | ✅ Working | Query param: `?campaignId={id}` |
| `/campaign/Resume` | POST | ✅ Working | Query param: `?campaignId={id}` |
| `/campaign/AddLeadsToListV2` | POST | ✅ Working | Requires ACTIVE campaign |
| `/campaign/Create` | POST | ❌ 404 | Not available |
| `/lead/GetLead` | POST | ✅ Working | Requires `profileUrl` |
| `/lead/UpdateStatus` | POST | ❌ 404 | Not available |
| `/inbox/GetConversationsV2` | POST | ✅ Working | Advanced filtering |
| `/stats/GetOverallStats` | POST | ✅ Working | Comprehensive analytics |
| `/list/GetAll` | POST | ✅ Working | Returns lead lists |
| `/list/CreateEmptyList` | POST | ✅ Working | Creates new lists |
| `/linkedinaccount/GetAll` | POST | ✅ Working | Returns LinkedIn accounts |
| `/MyNetwork/GetMyNetworkForSender` | POST | ✅ Working | Requires `senderId` |
| `/message/Send` | POST | ❌ 404 | Not available |
| `/templates/GetAll` | GET | ❌ 404 | Not available |
| `/social/Action` | POST | ❌ 404 | Not available |
| `/analytics/campaign/{id}` | GET | ❌ 404 | Not available |
| `/webhook/GetAll` | POST | ✅ Working | List webhooks |
| `/webhook/Create` | POST | ✅ Working | Create webhook |
| `/webhook/Delete` | POST | ✅ Working | Delete webhook |
| `/webhook/GetById` | GET | ✅ Working | Get webhook details |
| `/webhook/Update` | POST | ✅ Working | Update webhook |

**Success Rate**: 16/22 endpoints working (72.7%)
