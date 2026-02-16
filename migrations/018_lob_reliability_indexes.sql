-- V2 Stage 5: Lob reliability query/index hardening

BEGIN;

-- Dead-letter and replay/operator filtering for Lob webhook events
CREATE INDEX IF NOT EXISTS idx_webhook_events_lob_status_org_created
ON webhook_events (status, org_id, created_at DESC)
WHERE provider_slug = 'lob';

CREATE INDEX IF NOT EXISTS idx_webhook_events_lob_reason_created
ON webhook_events ((payload->'_dead_letter'->>'reason'), created_at DESC)
WHERE provider_slug = 'lob';

CREATE INDEX IF NOT EXISTS idx_webhook_events_lob_org_company_created
ON webhook_events (org_id, company_id, created_at DESC)
WHERE provider_slug = 'lob';

-- Direct-mail analytics range scans (tenant-scoped and status/type sliced)
CREATE INDEX IF NOT EXISTS idx_company_direct_mail_pieces_org_company_created_live
ON company_direct_mail_pieces (org_id, company_id, created_at DESC)
WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_company_direct_mail_pieces_org_company_updated_live
ON company_direct_mail_pieces (org_id, company_id, updated_at DESC)
WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_company_direct_mail_pieces_org_type_status_created_live
ON company_direct_mail_pieces (org_id, piece_type, status, created_at DESC)
WHERE deleted_at IS NULL;

COMMIT;
