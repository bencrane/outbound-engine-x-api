-- Phase 2: webhook event idempotency and audit storage

BEGIN;

CREATE TABLE IF NOT EXISTS webhook_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    provider_slug TEXT NOT NULL,
    event_key TEXT NOT NULL,
    event_type TEXT,
    org_id UUID,
    company_id UUID,
    payload JSONB NOT NULL,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_webhook_events_provider_event_key_unique
ON webhook_events (provider_slug, event_key);

CREATE INDEX IF NOT EXISTS idx_webhook_events_created_at
ON webhook_events (created_at DESC);

COMMIT;
