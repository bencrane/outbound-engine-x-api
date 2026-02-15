-- Phase 2: campaign lead mappings

BEGIN;

CREATE TABLE IF NOT EXISTS company_campaign_leads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    company_campaign_id UUID NOT NULL REFERENCES company_campaigns(id) ON DELETE CASCADE,
    provider_id UUID NOT NULL REFERENCES providers(id),
    external_lead_id TEXT NOT NULL,
    email TEXT,
    first_name TEXT,
    last_name TEXT,
    company_name TEXT,
    title TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    category TEXT,
    raw_payload JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);

ALTER TABLE company_campaign_leads
DROP CONSTRAINT IF EXISTS company_campaign_leads_company_same_org_fk,
ADD CONSTRAINT company_campaign_leads_company_same_org_fk
FOREIGN KEY (company_id, org_id)
REFERENCES companies (id, org_id)
ON DELETE CASCADE
DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE company_campaign_leads
DROP CONSTRAINT IF EXISTS company_campaign_leads_campaign_same_org_fk,
ADD CONSTRAINT company_campaign_leads_campaign_same_org_fk
FOREIGN KEY (company_campaign_id, org_id)
REFERENCES company_campaigns (id, org_id)
ON DELETE CASCADE
DEFERRABLE INITIALLY IMMEDIATE;

CREATE UNIQUE INDEX IF NOT EXISTS idx_company_campaign_leads_unique_active
ON company_campaign_leads (company_campaign_id, provider_id, external_lead_id)
WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_company_campaign_leads_org_campaign
ON company_campaign_leads (org_id, company_campaign_id)
WHERE deleted_at IS NULL;

COMMIT;
