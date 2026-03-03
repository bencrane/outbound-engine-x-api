BEGIN;

CREATE TABLE IF NOT EXISTS campaign_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    company_campaign_id UUID NOT NULL REFERENCES company_campaigns(id) ON DELETE CASCADE,
    company_campaign_lead_id UUID REFERENCES company_campaign_leads(id) ON DELETE SET NULL,
    event_type TEXT NOT NULL,
    channel TEXT,
    provider_slug TEXT,
    step_order INTEGER,
    payload JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_campaign_events_org_campaign
ON campaign_events (org_id, company_campaign_id);

CREATE INDEX IF NOT EXISTS idx_campaign_events_lead
ON campaign_events (company_campaign_lead_id)
WHERE company_campaign_lead_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_campaign_events_type
ON campaign_events (event_type);

CREATE INDEX IF NOT EXISTS idx_campaign_events_created
ON campaign_events (created_at DESC);

COMMIT;
