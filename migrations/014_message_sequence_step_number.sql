-- Phase 3: sequence-step attribution support for campaign messages

BEGIN;

ALTER TABLE company_campaign_messages
ADD COLUMN IF NOT EXISTS sequence_step_number INTEGER;

ALTER TABLE company_campaign_messages
DROP CONSTRAINT IF EXISTS company_campaign_messages_sequence_step_number_check,
ADD CONSTRAINT company_campaign_messages_sequence_step_number_check
CHECK (sequence_step_number IS NULL OR sequence_step_number >= 1);

CREATE INDEX IF NOT EXISTS idx_company_campaign_messages_org_campaign_step
ON company_campaign_messages (org_id, company_campaign_id, sequence_step_number)
WHERE deleted_at IS NULL;

COMMIT;
