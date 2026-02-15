-- Phase 2 foundation: company campaign mappings for provider-backed outreach

BEGIN;

CREATE TABLE IF NOT EXISTS company_campaigns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    provider_id UUID NOT NULL REFERENCES providers(id),
    external_campaign_id TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'DRAFTED',
    created_by_user_id UUID REFERENCES users(id),
    raw_payload JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);

ALTER TABLE company_campaigns
DROP CONSTRAINT IF EXISTS company_campaigns_status_check,
ADD CONSTRAINT company_campaigns_status_check
CHECK (status IN ('DRAFTED', 'ACTIVE', 'PAUSED', 'STOPPED', 'COMPLETED'));

ALTER TABLE company_campaigns
DROP CONSTRAINT IF EXISTS company_campaigns_id_org_id_unique,
ADD CONSTRAINT company_campaigns_id_org_id_unique UNIQUE (id, org_id);

ALTER TABLE company_campaigns
DROP CONSTRAINT IF EXISTS company_campaigns_company_same_org_fk,
ADD CONSTRAINT company_campaigns_company_same_org_fk
FOREIGN KEY (company_id, org_id)
REFERENCES companies (id, org_id)
ON DELETE CASCADE
DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE company_campaigns
DROP CONSTRAINT IF EXISTS company_campaigns_creator_same_org_fk,
ADD CONSTRAINT company_campaigns_creator_same_org_fk
FOREIGN KEY (created_by_user_id, org_id)
REFERENCES users (id, org_id)
ON DELETE SET NULL
DEFERRABLE INITIALLY IMMEDIATE;

CREATE UNIQUE INDEX IF NOT EXISTS idx_company_campaigns_company_provider_external_unique
ON company_campaigns (company_id, provider_id, external_campaign_id)
WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_company_campaigns_org_company
ON company_campaigns (org_id, company_id)
WHERE deleted_at IS NULL;

COMMIT;
