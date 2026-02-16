# EmailBison Rollout Release Note (2026-02-16)

Status:
“EmailBison rollout complete for all discoverable contracts; remaining work is provider-contract gated only (webhook signature verification + 3 missing update/delete endpoints).”

Scope closed as v1 complete with gated items only.

Blocked items:
- `SUPPORT-EMAILBISON-WEBHOOK-SIGNATURE-2026-02-16`
- `custom_variables.update` -> `blocked_contract_missing`
- `custom_variables.delete` -> `blocked_contract_missing`
- `tags.update` -> `blocked_contract_missing`

Guardrail:
- Do not implement webhook signature verification until provider contract is published and the support ticket is resolved.
