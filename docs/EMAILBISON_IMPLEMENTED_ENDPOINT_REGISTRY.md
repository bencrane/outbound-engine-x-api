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

## Guardrails

- Phase 3 webhook signature verification remains blocked until `SUPPORT-EMAILBISON-WEBHOOK-SIGNATURE-2026-02-16` is resolved.
