BEGIN;

CREATE TABLE IF NOT EXISTS campaign_lead_step_content (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    company_campaign_id UUID NOT NULL REFERENCES company_campaigns(id) ON DELETE CASCADE,
    company_campaign_lead_id UUID NOT NULL REFERENCES company_campaign_leads(id) ON DELETE CASCADE,
    step_order INTEGER NOT NULL,
    action_config_override JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_lead_step_content_unique
ON campaign_lead_step_content (company_campaign_lead_id, step_order);

CREATE INDEX IF NOT EXISTS idx_lead_step_content_campaign
ON campaign_lead_step_content (company_campaign_id);

CREATE INDEX IF NOT EXISTS idx_lead_step_content_org
ON campaign_lead_step_content (org_id);

COMMIT;
