-- Directive 1: Multi-channel campaign schema foundation

BEGIN;

-- 1a. Alter company_campaigns for campaign-type aware behavior
ALTER TABLE company_campaigns
ADD COLUMN IF NOT EXISTS campaign_type TEXT NOT NULL DEFAULT 'single_channel';

ALTER TABLE company_campaigns
DROP CONSTRAINT IF EXISTS company_campaigns_campaign_type_check,
ADD CONSTRAINT company_campaigns_campaign_type_check
CHECK (campaign_type IN ('single_channel', 'multi_channel'));

ALTER TABLE company_campaigns
ALTER COLUMN provider_id DROP NOT NULL;

-- 1b. Normalized multi-channel sequence steps
CREATE TABLE IF NOT EXISTS campaign_sequence_steps (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    company_campaign_id UUID NOT NULL REFERENCES company_campaigns(id) ON DELETE CASCADE,
    step_order INTEGER NOT NULL,
    channel TEXT NOT NULL,
    provider_id UUID NOT NULL REFERENCES providers(id),
    action_type TEXT NOT NULL,
    action_config JSONB NOT NULL DEFAULT '{}',
    delay_days INTEGER NOT NULL DEFAULT 0,
    execution_mode TEXT NOT NULL DEFAULT 'direct_single_touch',
    skip_if JSONB,
    provider_campaign_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);

ALTER TABLE campaign_sequence_steps
DROP CONSTRAINT IF EXISTS campaign_sequence_steps_channel_check,
ADD CONSTRAINT campaign_sequence_steps_channel_check
CHECK (channel IN ('email', 'linkedin', 'direct_mail'));

ALTER TABLE campaign_sequence_steps
DROP CONSTRAINT IF EXISTS campaign_sequence_steps_execution_mode_check,
ADD CONSTRAINT campaign_sequence_steps_execution_mode_check
CHECK (execution_mode IN ('direct_single_touch', 'campaign_mediated'));

ALTER TABLE campaign_sequence_steps
DROP CONSTRAINT IF EXISTS campaign_sequence_steps_campaign_same_org_fk,
ADD CONSTRAINT campaign_sequence_steps_campaign_same_org_fk
FOREIGN KEY (company_campaign_id, org_id)
REFERENCES company_campaigns (id, org_id)
ON DELETE CASCADE
DEFERRABLE INITIALLY IMMEDIATE;

CREATE UNIQUE INDEX IF NOT EXISTS idx_campaign_sequence_steps_order_unique
ON campaign_sequence_steps (company_campaign_id, step_order)
WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_campaign_sequence_steps_org_campaign
ON campaign_sequence_steps (org_id, company_campaign_id)
WHERE deleted_at IS NULL;

-- 1c. Per-lead sequence progress state
CREATE TABLE IF NOT EXISTS campaign_lead_progress (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    company_campaign_id UUID NOT NULL REFERENCES company_campaigns(id) ON DELETE CASCADE,
    company_campaign_lead_id UUID NOT NULL REFERENCES company_campaign_leads(id) ON DELETE CASCADE,
    current_step_id UUID REFERENCES campaign_sequence_steps(id) ON DELETE SET NULL,
    current_step_order INTEGER NOT NULL DEFAULT 1,
    step_status TEXT NOT NULL DEFAULT 'pending',
    next_execute_at TIMESTAMPTZ,
    executed_at TIMESTAMPTZ,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE campaign_lead_progress
DROP CONSTRAINT IF EXISTS campaign_lead_progress_step_status_check,
ADD CONSTRAINT campaign_lead_progress_step_status_check
CHECK (step_status IN ('pending', 'executing', 'executed', 'skipped', 'failed', 'completed'));

ALTER TABLE campaign_lead_progress
DROP CONSTRAINT IF EXISTS campaign_lead_progress_campaign_same_org_fk,
ADD CONSTRAINT campaign_lead_progress_campaign_same_org_fk
FOREIGN KEY (company_campaign_id, org_id)
REFERENCES company_campaigns (id, org_id)
ON DELETE CASCADE
DEFERRABLE INITIALLY IMMEDIATE;

CREATE UNIQUE INDEX IF NOT EXISTS idx_campaign_lead_progress_lead_unique
ON campaign_lead_progress (company_campaign_id, company_campaign_lead_id);

CREATE INDEX IF NOT EXISTS idx_campaign_lead_progress_pending
ON campaign_lead_progress (next_execute_at)
WHERE step_status = 'pending' AND next_execute_at IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_campaign_lead_progress_org_campaign
ON campaign_lead_progress (org_id, company_campaign_id);

-- 1d. Per-provider external identifier mapping for campaign leads
CREATE TABLE IF NOT EXISTS campaign_lead_provider_ids (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    company_campaign_lead_id UUID NOT NULL REFERENCES company_campaign_leads(id) ON DELETE CASCADE,
    provider_id UUID NOT NULL REFERENCES providers(id),
    external_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_campaign_lead_provider_ids_unique
ON campaign_lead_provider_ids (company_campaign_lead_id, provider_id);

CREATE INDEX IF NOT EXISTS idx_campaign_lead_provider_ids_org
ON campaign_lead_provider_ids (org_id);

COMMIT;
