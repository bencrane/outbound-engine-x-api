-- Phase 2: campaign message history snapshots

BEGIN;

CREATE TABLE IF NOT EXISTS company_campaign_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    company_campaign_id UUID NOT NULL REFERENCES company_campaigns(id) ON DELETE CASCADE,
    company_campaign_lead_id UUID REFERENCES company_campaign_leads(id) ON DELETE SET NULL,
    provider_id UUID NOT NULL REFERENCES providers(id),
    external_message_id TEXT NOT NULL,
    external_lead_id TEXT,
    direction TEXT NOT NULL DEFAULT 'outbound',
    subject TEXT,
    body TEXT,
    sent_at TIMESTAMPTZ,
    raw_payload JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);

ALTER TABLE company_campaign_messages
DROP CONSTRAINT IF EXISTS company_campaign_messages_company_same_org_fk,
ADD CONSTRAINT company_campaign_messages_company_same_org_fk
FOREIGN KEY (company_id, org_id)
REFERENCES companies (id, org_id)
ON DELETE CASCADE
DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE company_campaign_messages
DROP CONSTRAINT IF EXISTS company_campaign_messages_campaign_same_org_fk,
ADD CONSTRAINT company_campaign_messages_campaign_same_org_fk
FOREIGN KEY (company_campaign_id, org_id)
REFERENCES company_campaigns (id, org_id)
ON DELETE CASCADE
DEFERRABLE INITIALLY IMMEDIATE;

CREATE UNIQUE INDEX IF NOT EXISTS idx_company_campaign_messages_unique_active
ON company_campaign_messages (company_campaign_id, provider_id, external_message_id)
WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_company_campaign_messages_org_campaign
ON company_campaign_messages (org_id, company_campaign_id)
WHERE deleted_at IS NULL;

COMMIT;
