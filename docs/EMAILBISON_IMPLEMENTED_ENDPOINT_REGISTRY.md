# EmailBison Implemented Endpoint Registry

Generated: 2026-02-16

Canonical source: live `user-emailbison` API spec/tool output.

Purpose: strict proof of what EmailBison endpoints are implemented in this repo, by method + path + client function.

## Source Of Truth In Code

- Registry constant: `src/providers/emailbison/client.py` -> `EMAILBISON_IMPLEMENTED_ENDPOINT_REGISTRY`
- Guard test: `tests/test_emailbison_client.py::test_registry_covers_all_public_client_methods`

If a new public EmailBison client method is added without registry entry, tests must fail.

## Slice 1 Coverage (Leads + Lead Lifecycle)

- `GET /api/leads` -> `list_leads()`
- `POST /api/leads` -> `create_lead()`
- `POST /api/leads/multiple` -> `create_leads_bulk()`
- `POST /api/leads/create-or-update/multiple` -> `create_or_update_leads_bulk()`
- `GET /api/leads/{lead_id}` -> `get_lead()`
- `PATCH|PUT /api/leads/{lead_id}` -> `update_lead()`
- `PATCH /api/leads/{lead_id}/update-status` -> `update_lead_status()`
- `PATCH /api/leads/{lead_id}/unsubscribe` -> `unsubscribe_lead()`
- `DELETE /api/leads/{lead_id}` -> `delete_lead()`
- `GET /api/campaigns/{campaign_id}/leads` -> `list_campaign_leads()`
- `POST /api/campaigns/{campaign_id}/leads/attach-leads` -> `attach_leads_to_campaign()`
- `POST /api/campaigns/{campaign_id}/leads/attach-lead-list` -> `attach_lead_list_to_campaign()`
- `POST /api/campaigns/{campaign_id}/leads/stop-future-emails` -> `stop_future_emails_for_leads()`
- `DELETE /api/campaigns/{campaign_id}/leads` -> `remove_leads_from_campaign()`

## Slice 2 Coverage (Campaigns Advanced)

- `GET /api/campaigns/{campaign_id}/sequence-steps` -> `get_campaign_sequence_steps()`
- `POST /api/campaigns/{campaign_id}/sequence-steps` -> `create_campaign_sequence_steps()`
- `GET /api/campaigns/{campaign_id}/schedule` -> `get_campaign_schedule()`
- `POST /api/campaigns/{campaign_id}/schedule` -> `create_campaign_schedule()`
- `GET /api/campaigns/{campaign_id}/sending-schedule` -> `get_campaign_sending_schedule()`
- `GET /api/campaigns/{campaign_id}/sender-emails` -> `get_campaign_sender_emails()`
- `GET /api/campaigns/{campaign_id}/line-area-chart-stats` -> `get_campaign_line_area_chart_stats()`

## Slice 3 Coverage (Inbox + Replies)

- `GET /api/replies` -> `list_replies()`
- `GET /api/replies/{id}` -> `get_reply()`
- `GET /api/replies/{reply_id}/conversation-thread` -> `get_reply_conversation_thread()`
- `GET /api/campaigns/{campaign_id}/replies` -> `list_campaign_replies()`
- `GET /api/leads/{lead_id}/replies` -> `list_lead_replies()`

## Slice 4 Coverage (Sender Emails + Warmup + Healthcheck)

- `GET /api/sender-emails` -> `list_sender_emails()`
- `GET /api/sender-emails/{senderEmailId}` -> `get_sender_email()`
- `PATCH /api/sender-emails/{senderEmailId}` -> `update_sender_email()`
- `DELETE /api/sender-emails/{senderEmailId}` -> `delete_sender_email()`
- `GET /api/warmup/sender-emails` -> `list_sender_emails_with_warmup_stats()`
- `GET /api/warmup/sender-emails/{senderEmailId}` -> `get_sender_email_warmup_details()`
- `PATCH /api/warmup/sender-emails/enable` -> `enable_warmup_for_sender_emails()`
- `PATCH /api/warmup/sender-emails/disable` -> `disable_warmup_for_sender_emails()`
- `PATCH /api/warmup/sender-emails/update-daily-warmup-limits` -> `update_sender_email_daily_warmup_limits()`
- `POST /api/sender-emails/{senderEmailId}/check-mx-records` -> `check_sender_email_mx_records()`
- `POST /api/sender-emails/bulk-check-missing-mx-records` -> `bulk_check_missing_mx_records()`

## Guardrails

- Phase 3 webhook signature verification remains blocked until `SUPPORT-EMAILBISON-WEBHOOK-SIGNATURE-2026-02-16` is resolved.
