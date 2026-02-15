-- Phase 2: campaign sequence snapshots mapped to company campaigns

BEGIN;

CREATE TABLE IF NOT EXISTS company_campaign_sequences (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    company_campaign_id UUID NOT NULL REFERENCES company_campaigns(id) ON DELETE CASCADE,
    version INTEGER NOT NULL DEFAULT 1,
    sequence_payload JSONB NOT NULL,
    created_by_user_id UUID REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);

ALTER TABLE company_campaign_sequences
DROP CONSTRAINT IF EXISTS company_campaign_sequences_campaign_same_org_fk,
ADD CONSTRAINT company_campaign_sequences_campaign_same_org_fk
FOREIGN KEY (company_campaign_id, org_id)
REFERENCES company_campaigns (id, org_id)
ON DELETE CASCADE
DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE company_campaign_sequences
DROP CONSTRAINT IF EXISTS company_campaign_sequences_creator_same_org_fk,
ADD CONSTRAINT company_campaign_sequences_creator_same_org_fk
FOREIGN KEY (created_by_user_id, org_id)
REFERENCES users (id, org_id)
ON DELETE SET NULL
DEFERRABLE INITIALLY IMMEDIATE;

CREATE UNIQUE INDEX IF NOT EXISTS idx_company_campaign_sequences_campaign_version_unique
ON company_campaign_sequences (company_campaign_id, version)
WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_company_campaign_sequences_org_campaign
ON company_campaign_sequences (org_id, company_campaign_id)
WHERE deleted_at IS NULL;

COMMIT;
