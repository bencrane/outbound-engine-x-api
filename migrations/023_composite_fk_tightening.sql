-- Tighten composite FK constraints flagged in Directive 1
-- Ensures campaign_lead_provider_ids and campaign_lead_progress
-- have org-consistent references

BEGIN;

-- campaign_lead_provider_ids: ensure lead belongs to same org
-- First add org_id to the unique constraint on company_campaign_leads so we can reference it
-- (company_campaign_leads already has org_id column, just need the composite unique for FK)

-- Add composite unique on company_campaign_leads if not exists
CREATE UNIQUE INDEX IF NOT EXISTS idx_company_campaign_leads_id_org
ON company_campaign_leads (id, org_id);

-- Add composite FK on campaign_lead_provider_ids
ALTER TABLE campaign_lead_provider_ids
DROP CONSTRAINT IF EXISTS campaign_lead_provider_ids_lead_same_org_fk,
ADD CONSTRAINT campaign_lead_provider_ids_lead_same_org_fk
FOREIGN KEY (company_campaign_lead_id, org_id)
REFERENCES company_campaign_leads (id, org_id)
ON DELETE CASCADE
DEFERRABLE INITIALLY IMMEDIATE;

-- Add composite unique on campaign_sequence_steps so progress can reference it with org
CREATE UNIQUE INDEX IF NOT EXISTS idx_campaign_sequence_steps_id_org
ON campaign_sequence_steps (id, org_id);

-- campaign_lead_progress: ensure step belongs to same org
ALTER TABLE campaign_lead_progress
DROP CONSTRAINT IF EXISTS campaign_lead_progress_step_same_org_fk,
ADD CONSTRAINT campaign_lead_progress_step_same_org_fk
FOREIGN KEY (current_step_id, org_id)
REFERENCES campaign_sequence_steps (id, org_id)
ON DELETE SET NULL
DEFERRABLE INITIALLY IMMEDIATE;

COMMIT;
