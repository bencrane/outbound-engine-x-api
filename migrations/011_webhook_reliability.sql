-- Phase 3: webhook durability and replay bookkeeping

BEGIN;

ALTER TABLE webhook_events
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'processed',
    ADD COLUMN IF NOT EXISTS replay_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS last_replay_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_error TEXT;

ALTER TABLE webhook_events
    DROP CONSTRAINT IF EXISTS webhook_events_status_check;

ALTER TABLE webhook_events
    ADD CONSTRAINT webhook_events_status_check
    CHECK (status IN ('processed', 'replayed', 'failed', 'dead_letter'));

CREATE INDEX IF NOT EXISTS idx_webhook_events_provider_status_created
ON webhook_events (provider_slug, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_webhook_events_org_company_created
ON webhook_events (org_id, company_id, created_at DESC);

COMMIT;
