-- Phase 3: durable observability metric snapshot sink

BEGIN;

CREATE TABLE IF NOT EXISTS observability_metric_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source TEXT NOT NULL,
    request_id TEXT,
    counters JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_observability_metric_snapshots_created
ON observability_metric_snapshots (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_observability_metric_snapshots_source_created
ON observability_metric_snapshots (source, created_at DESC);

COMMIT;
