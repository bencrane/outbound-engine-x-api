-- Phase 3: track campaign-level message reconciliation health

BEGIN;

ALTER TABLE company_campaigns
ADD COLUMN IF NOT EXISTS message_sync_status TEXT,
ADD COLUMN IF NOT EXISTS last_message_sync_at TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS last_message_sync_error TEXT;

CREATE INDEX IF NOT EXISTS idx_company_campaigns_message_sync_status
ON company_campaigns (org_id, message_sync_status)
WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_company_campaigns_last_message_sync_at
ON company_campaigns (org_id, last_message_sync_at DESC)
WHERE deleted_at IS NULL;

COMMIT;
