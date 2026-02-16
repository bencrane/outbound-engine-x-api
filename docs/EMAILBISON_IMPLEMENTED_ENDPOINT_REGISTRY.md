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

Notes:
- Warmup reads always pass explicit `start_date` and `end_date`.
- Healthcheck is currently canonicalized to MX-record endpoints only (`check-mx-records`, `bulk-check-missing-mx-records`); no broader sender health endpoint surfaced in live `user-emailbison` spec output.

## Slice 5 Coverage (Tags + Variables + Blocklists)

- `GET /api/tags` -> `list_tags()`
- `POST /api/tags` -> `create_tag()`
- `GET /api/tags/{id}` -> `get_tag()`
- `DELETE /api/tags/{tag_id}` -> `delete_tag()`
- `POST /api/tags/attach-to-campaigns` -> `attach_tags_to_campaigns()`
- `POST /api/tags/remove-from-campaigns` -> `remove_tags_from_campaigns()`
- `POST /api/tags/attach-to-leads` -> `attach_tags_to_leads()`
- `POST /api/tags/remove-from-leads` -> `remove_tags_from_leads()`
- `POST /api/tags/attach-to-sender-emails` -> `attach_tags_to_sender_emails()`
- `POST /api/tags/remove-from-sender-emails` -> `remove_tags_from_sender_emails()`
- `GET /api/custom-variables` -> `list_custom_variables()`
- `POST /api/custom-variables` -> `create_custom_variable()`
- `GET /api/blacklisted-emails` -> `list_blacklisted_emails()`
- `POST /api/blacklisted-emails` -> `create_blacklisted_email()`
- `POST /api/blacklisted-emails/bulk` -> `bulk_create_blacklisted_emails()`
- `DELETE /api/blacklisted-emails/{blacklisted_email_id}` -> `delete_blacklisted_email()`
- `GET /api/blacklisted-domains` -> `list_blacklisted_domains()`
- `POST /api/blacklisted-domains` -> `create_blacklisted_domain()`
- `POST /api/blacklisted-domains/bulk` -> `bulk_create_blacklisted_domains()`
- `DELETE /api/blacklisted-domains/{blacklisted_domain_id}` -> `delete_blacklisted_domain()`

## Slice 6 Coverage (Workspaces + Settings + Analytics/Stats)

- `GET /api/users` -> `get_workspace_account_details()`
- `GET /api/workspaces/v1.1/stats` -> `get_workspace_stats()`
- `GET /api/workspaces/v1.1/master-inbox-settings` -> `get_workspace_master_inbox_settings()`
- `PATCH /api/workspaces/v1.1/master-inbox-settings` -> `update_workspace_master_inbox_settings()`
- `GET /api/campaign-events/stats` -> `get_campaign_events_stats()`

## Slice 7 Coverage (Webhook Management Surface Only)

- `GET /api/webhook-url` -> `list_webhooks()`
- `POST /api/webhook-url` -> `create_webhook()`
- `GET /api/webhook-url/{id}` -> `get_webhook()`
- `PUT /api/webhook-url/{id}` -> `update_webhook()`
- `DELETE /api/webhook-url/{id|webhook_url_id}` -> `delete_webhook()` (tolerant delete path mapping)
- `GET /api/webhook-events/event-types` -> `get_webhook_event_types()`
- `GET /api/webhook-events/sample-payload` -> `get_sample_webhook_payload()`
- `POST /api/webhook-events/test-event` -> `send_test_webhook_event()`

Notes:
- This slice covers management/test/sample/event-types only.
- Inbound webhook signature verification remains blocked on `SUPPORT-EMAILBISON-WEBHOOK-SIGNATURE-2026-02-16`.

## Slice 8 Coverage (Export + Analytics + Bulk Parity)

- `DELETE /api/campaigns/bulk` -> `bulk_delete_campaigns()`
- `PATCH /api/sender-emails/signatures/bulk` -> `bulk_update_sender_email_signatures()`
- `PATCH /api/sender-emails/daily-limits/bulk` -> `bulk_update_sender_email_daily_limits()`
- `POST /api/sender-emails/bulk` -> `bulk_create_sender_emails()`
- `POST /api/leads/bulk/csv` -> `bulk_create_leads_csv()`
- `PATCH /api/leads/bulk-update-status` -> `bulk_update_lead_status()`
- `DELETE /api/leads/bulk` -> `bulk_delete_leads()`

Notes:
- These endpoints complete the discoverable bulk/export-adjacent parity from current live API spec output.
- Existing stats/analytics endpoints from Slice 6 remain canonical (`/api/workspaces/v1.1/stats`, `/api/campaign-events/stats`).

## Contract-Limited Gaps (Registry Status)

Source of truth in code: `src/providers/emailbison/client.py` -> `EMAILBISON_CONTRACT_STATUS_REGISTRY`

- `custom_variables.update` -> `blocked_contract_missing`
  - Evidence: live `user-emailbison` spec output currently surfaces `GET|POST /api/custom-variables` only.
- `custom_variables.delete` -> `blocked_contract_missing`
  - Evidence: live `user-emailbison` spec output currently surfaces `GET|POST /api/custom-variables` only.
- `tags.update` -> `blocked_contract_missing`
  - Evidence: live `user-emailbison` spec output currently surfaces `GET|POST /api/tags`, `GET /api/tags/{id}`, `DELETE /api/tags/{tag_id}`; no update path surfaced.

## Guardrails

- Phase 3 webhook signature verification remains blocked until `SUPPORT-EMAILBISON-WEBHOOK-SIGNATURE-2026-02-16` is resolved.
