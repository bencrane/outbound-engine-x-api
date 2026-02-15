-- Phase 2 foundation: company inbox mappings for provider-backed email outreach

BEGIN;

CREATE TABLE IF NOT EXISTS company_inboxes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    provider_id UUID NOT NULL REFERENCES providers(id),
    external_account_id TEXT NOT NULL,
    email TEXT NOT NULL,
    display_name TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    warmup_enabled BOOLEAN,
    raw_payload JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);

ALTER TABLE company_inboxes
DROP CONSTRAINT IF EXISTS company_inboxes_status_check,
ADD CONSTRAINT company_inboxes_status_check
CHECK (status IN ('active', 'inactive'));

ALTER TABLE company_inboxes
DROP CONSTRAINT IF EXISTS company_inboxes_company_same_org_fk,
ADD CONSTRAINT company_inboxes_company_same_org_fk
FOREIGN KEY (company_id, org_id)
REFERENCES companies (id, org_id)
ON DELETE CASCADE
DEFERRABLE INITIALLY IMMEDIATE;

CREATE UNIQUE INDEX IF NOT EXISTS idx_company_inboxes_company_provider_external_unique
ON company_inboxes (company_id, provider_id, external_account_id)
WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_company_inboxes_org_company
ON company_inboxes (org_id, company_id)
WHERE deleted_at IS NULL;

COMMIT;
